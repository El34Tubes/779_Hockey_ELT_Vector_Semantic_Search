"""
Deep analysis of JSON structure to prepare for ETL
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import json
from config.config import Config

def analyze_json_file(filename):
    """Analyze a JSON file structure"""
    filepath = os.path.join(Config.DATA_DIR, filename)

    if not os.path.exists(filepath):
        print(f"✗ File not found: {filepath}")
        print(f"  Run 'python exploration/explore_sportdb.py' first")
        return None

    with open(filepath, 'r') as f:
        data = json.load(f)

    return data

def explore_nested_structure(obj, path="root", max_depth=4, current_depth=0):
    """Recursively explore JSON structure"""

    if current_depth >= max_depth:
        return

    indent = "  " * current_depth

    if isinstance(obj, dict):
        if current_depth < 3:
            print(f"{indent}Object with {len(obj)} keys:")

        for key, value in list(obj.items())[:10]:
            value_type = type(value).__name__

            if current_depth < 3:
                print(f"{indent}  {key}: {value_type}", end="")

                if isinstance(value, list):
                    print(f" (length: {len(value)})")
                elif isinstance(value, dict):
                    print(f" ({len(value)} keys)")
                elif isinstance(value, str):
                    preview = value[:50] + "..." if len(value) > 50 else value
                    print(f" = '{preview}'")
                else:
                    print(f" = {value}")

            if isinstance(value, (dict, list)):
                explore_nested_structure(value, f"{path}.{key}", max_depth, current_depth + 1)

    elif isinstance(obj, list):
        if len(obj) > 0:
            if current_depth < 3:
                print(f"{indent}Array with {len(obj)} items")
                print(f"{indent}First item:")
            explore_nested_structure(obj[0], f"{path}[0]", max_depth, current_depth + 1)

def identify_warehouse_fields(data):
    """Identify fields we need for warehouse"""

    print("\n" + "=" * 60)
    print("KEY FIELDS FOR WAREHOUSE")
    print("=" * 60)

    game_list = []
    if isinstance(data, dict):
        if 'events' in data:
            game_list = data['events']
            array_name = 'events'
        elif 'games' in data:
            game_list = data['games']
            array_name = 'games'
        else:
            array_name = 'unknown'
    elif isinstance(data, list):
        game_list = data
        array_name = 'root'

    if not game_list:
        print("No games found in data")
        return

    print(f"\nAnalyzing {len(game_list)} games from '{array_name}' array")

    if len(game_list) > 0:
        first_game = game_list[0]

        print(f"\nFirst game structure:")
        print(f"Type: {type(first_game)}")

        if isinstance(first_game, dict):
            print(f"Keys ({len(first_game)}): {list(first_game.keys())}")

            categories = {
                'Identifiers': [],
                'Teams': [],
                'Scores': [],
                'Timing': [],
                'Status': [],
                'Venue': [],
                'Tournament': []
            }

            for key, value in first_game.items():
                key_lower = key.lower()

                if any(x in key_lower for x in ['id']):
                    categories['Identifiers'].append((key, type(value).__name__, value))
                elif any(x in key_lower for x in ['team', 'home', 'away']):
                    categories['Teams'].append((key, type(value).__name__, str(value)[:100]))
                elif any(x in key_lower for x in ['score', 'goal']):
                    categories['Scores'].append((key, type(value).__name__, value))
                elif any(x in key_lower for x in ['time', 'date', 'timestamp', 'stage']):
                    categories['Timing'].append((key, type(value).__name__, value))
                elif any(x in key_lower for x in ['status', 'state']):
                    categories['Status'].append((key, type(value).__name__, value))
                elif any(x in key_lower for x in ['venue', 'location']):
                    categories['Venue'].append((key, type(value).__name__, str(value)[:100]))
                elif any(x in key_lower for x in ['tournament', 'league', 'competition']):
                    categories['Tournament'].append((key, type(value).__name__, str(value)[:100]))

            for category, fields in categories.items():
                if fields:
                    print(f"\n{category}:")
                    for field_name, field_type, field_value in fields:
                        print(f"  {field_name} ({field_type}): {field_value}")

def generate_json_table_template(data):
    """Generate Oracle JSON_TABLE template"""

    print("\n" + "=" * 60)
    print("ORACLE JSON_TABLE TEMPLATE")
    print("=" * 60)

    array_path = "$.events[*]"
    if isinstance(data, dict):
        if 'events' in data:
            array_path = "$.events[*]"
        elif 'games' in data:
            array_path = "$.games[*]"
    elif isinstance(data, list):
        array_path = "$[*]"

    print(f"\n-- Use this in your staging view:")
    print(f"""
CREATE OR REPLACE VIEW raw_schema.stg_sportdb_games AS
SELECT
    r.ingestion_id,
    r.ingestion_timestamp,
    games.*
FROM raw_schema.sportdb_games r,
    JSON_TABLE(r.api_response, '{array_path}'
        COLUMNS (
            -- TODO: Add actual field mappings based on your data
            game_id VARCHAR2(50) PATH '$.id',
            -- Add more fields here
        )
    ) games
WHERE r.processed = 'N';
""")

    print("\nTo complete this template:")
    print("1. Review the 'KEY FIELDS FOR WAREHOUSE' section above")
    print("2. Add appropriate COLUMNS for each field")
    print("3. Use correct JSON paths (e.g., '$.homeTeam.name')")

def create_field_inventory(data, output_file='field_analysis.txt'):
    """Create complete field inventory"""

    def collect_all_paths(obj, current_path="$", paths=None):
        if paths is None:
            paths = {}

        if isinstance(obj, dict):
            for key, value in obj.items():
                new_path = f"{current_path}.{key}"
                value_type = type(value).__name__

                if isinstance(value, (str, int, float, bool)):
                    sample = str(value)[:100]
                elif isinstance(value, list):
                    sample = f"Array[{len(value)}]"
                elif isinstance(value, dict):
                    sample = f"Object[{len(value)} keys]"
                else:
                    sample = value_type

                paths[new_path] = (value_type, sample)

                if isinstance(value, dict):
                    collect_all_paths(value, new_path, paths)
                elif isinstance(value, list) and len(value) > 0:
                    collect_all_paths(value[0], f"{new_path}[0]", paths)

        elif isinstance(obj, list) and len(obj) > 0:
            collect_all_paths(obj[0], f"{current_path}[0]", paths)

        return paths

    print("\n" + "=" * 60)
    print("GENERATING FIELD INVENTORY")
    print("=" * 60)

    paths = collect_all_paths(data)

    output_path = os.path.join(Config.DATA_DIR, output_file)
    with open(output_path, 'w') as f:
        f.write("COMPLETE FIELD INVENTORY\n")
        f.write("=" * 80 + "\n\n")

        for path in sorted(paths.keys()):
            value_type, sample = paths[path]
            f.write(f"{path}\n")
            f.write(f"  Type: {value_type}\n")
            f.write(f"  Sample: {sample}\n\n")

    print(f"✓ Field inventory saved to: {output_path}")
    print(f"  Total unique paths: {len(paths)}")

def main():
    print("=" * 60)
    print("JSON STRUCTURE ANALYSIS")
    print("=" * 60)

    filename = 'sample_hockey_response.json'
    print(f"\nAnalyzing: {filename}")

    data = analyze_json_file(filename)

    if not data:
        return 1

    print("\n" + "=" * 60)
    print("NESTED STRUCTURE")
    print("=" * 60)
    explore_nested_structure(data)

    identify_warehouse_fields(data)
    generate_json_table_template(data)
    create_field_inventory(data)

    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print("\n✓ Review the output above")
    print(f"✓ Check '{Config.DATA_DIR}/field_analysis.txt' for complete inventory")
    print("\nNext steps:")
    print("  1. Review the JSON structure")
    print("  2. Design your staging views")
    print("  3. Map fields to warehouse dimensions")

    return 0

if __name__ == "__main__":
    sys.exit(main())
