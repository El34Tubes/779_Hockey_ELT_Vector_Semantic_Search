"""
Comprehensive exploration of SportDB Hockey API
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import requests
import json
from datetime import datetime, timedelta
from config.config import Config

class SportDBExplorer:
    def __init__(self):
        Config.validate()
        self.api_key = Config.SPORTDB_API_KEY
        self.base_url = Config.SPORTDB_BASE_URL
        self.headers = {'X-API-Key': self.api_key}
        self.data_dir = Config.DATA_DIR

    def get_hockey_games(self, offset=0, tz=0):
        """
        Get hockey games for a specific day
        offset: 0=today, -1=yesterday, -7=week ago, etc.
        """
        url = f"{self.base_url}/api/flashscore/hockey/live"
        params = {'offset': offset, 'tz': tz}

        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                print(f"✓ Retrieved data for offset={offset}", end="")

                if offset == 0:
                    print(" (today)")
                elif offset < 0:
                    print(f" ({abs(offset)} days ago)")
                else:
                    print(f" ({offset} days from now)")

                return data
            else:
                print(f"✗ Error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"✗ Request error: {e}")
            return None

    def explore_response_structure(self, data):
        """Analyze the JSON structure"""
        if not data:
            print("No data to explore")
            return

        print("\n" + "=" * 60)
        print("RESPONSE STRUCTURE ANALYSIS")
        print("=" * 60)

        print(f"\nResponse type: {type(data)}")

        if isinstance(data, dict):
            print(f"Top-level keys: {list(data.keys())}")

            for key, value in data.items():
                print(f"\n'{key}':")
                print(f"  Type: {type(value).__name__}")

                if isinstance(value, list):
                    print(f"  Length: {len(value)}")
                    if len(value) > 0:
                        print(f"  First item type: {type(value[0]).__name__}")
                        if isinstance(value[0], dict):
                            print(f"  First item keys: {list(value[0].keys())[:10]}")
                elif isinstance(value, dict):
                    print(f"  Keys: {list(value.keys())[:10]}")

        elif isinstance(data, list):
            print(f"Response is a list with {len(data)} items")
            if len(data) > 0:
                print(f"First item type: {type(data[0]).__name__}")
                if isinstance(data[0], dict):
                    print(f"First item keys: {list(data[0].keys())}")

    def extract_game_details(self, data):
        """Extract key fields from games"""
        if not data:
            return []

        games = []
        game_list = []

        if isinstance(data, dict):
            if 'events' in data:
                game_list = data['events']
            elif 'games' in data:
                game_list = data['games']
            elif 'data' in data:
                game_list = data['data']
        elif isinstance(data, list):
            game_list = data

        print(f"\n" + "=" * 60)
        print(f"GAME DETAILS EXTRACTION")
        print("=" * 60)
        print(f"\nFound {len(game_list)} games")

        for i, game in enumerate(game_list[:5]):
            if not isinstance(game, dict):
                continue

            print(f"\n--- Game {i+1} ---")
            game_info = {}

            field_mappings = {
                'id': ['id', 'gameId', 'eventId', 'matchId'],
                'home_team': ['homeTeam', 'home_team', 'homeTeamName', 'home'],
                'away_team': ['awayTeam', 'away_team', 'awayTeamName', 'away'],
                'home_score': ['homeScore', 'home_score', 'scoreHome'],
                'away_score': ['awayScore', 'away_score', 'scoreAway'],
                'status': ['status', 'eventStageId', 'gameStatus'],
                'start_time': ['startTime', 'start_time', 'eventTime', 'timestamp'],
                'tournament': ['tournament', 'league', 'competition'],
            }

            for key, possible_names in field_mappings.items():
                for name in possible_names:
                    if name in game:
                        value = game[name]
                        if isinstance(value, dict) and 'name' in value:
                            game_info[key] = value['name']
                        else:
                            game_info[key] = value
                        break

            for key, value in game_info.items():
                print(f"  {key}: {value}")

            if len(game_info) < 3:
                print(f"  Available keys: {list(game.keys())[:15]}")

            games.append(game_info)

        if len(game_list) > 5:
            print(f"\n... and {len(game_list) - 5} more games")

        return games

    def save_sample_response(self, data, filename):
        """Save a sample response for analysis"""
        filepath = os.path.join(self.data_dir, filename)
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"✓ Saved to: {filepath}")

    def get_historical_week(self):
        """Get a week of historical games"""
        print("\n" + "=" * 60)
        print("FETCHING HISTORICAL WEEK")
        print("=" * 60)

        all_games = []
        for day_offset in range(-7, 0):
            print(f"\nDay offset {day_offset}:", end=" ")
            data = self.get_hockey_games(offset=day_offset)

            if data:
                game_count = 0
                if isinstance(data, dict):
                    if 'events' in data:
                        game_count = len(data['events'])
                    elif 'games' in data:
                        game_count = len(data['games'])
                elif isinstance(data, list):
                    game_count = len(data)

                print(f"  → {game_count} games found")

                all_games.append({
                    'offset': day_offset,
                    'date': (datetime.now() + timedelta(days=day_offset)).strftime('%Y-%m-%d'),
                    'game_count': game_count,
                    'data': data
                })

        return all_games

    def analyze_event_stage_ids(self, historical_data):
        """Analyze what eventStageId values appear in hockey"""
        print("\n" + "=" * 60)
        print("EVENT STAGE IDS IN HOCKEY DATA")
        print("=" * 60)

        stage_ids = set()

        for day_data in historical_data:
            data = day_data['data']
            game_list = []
            if isinstance(data, dict):
                game_list = data.get('events', data.get('games', []))
            elif isinstance(data, list):
                game_list = data

            for game in game_list:
                if isinstance(game, dict) and 'eventStageId' in game:
                    stage_ids.add(game['eventStageId'])

        print(f"\nUnique eventStageId values found: {sorted(stage_ids)}")

        stage_map = {
            1: "SCHEDULED",
            2: "LIVE",
            3: "FINISHED",
            14: "FIRST_PERIOD",
            15: "SECOND_PERIOD",
            16: "THIRD_PERIOD",
            38: "HALF_TIME",
            6: "EXTRA_TIME",
            242: "FULL_TIME"
        }

        print("\nMapped descriptions:")
        for stage_id in sorted(stage_ids):
            desc = stage_map.get(stage_id, 'UNKNOWN')
            print(f"  {stage_id:3d}: {desc}")

        return stage_ids

    def run_full_exploration(self):
        """Run complete exploration process"""
        print("=" * 60)
        print("NHL HOCKEY DATA EXPLORATION")
        print("=" * 60)

        print("\n[Step 1/6] Fetching today's games...")
        today_data = self.get_hockey_games(offset=0)

        if not today_data:
            print("\n✗ Failed to fetch data. Check API key and connection.")
            return False

        print("\n[Step 2/6] Analyzing structure...")
        self.explore_response_structure(today_data)

        print("\n[Step 3/6] Extracting game details...")
        games = self.extract_game_details(today_data)

        print("\n[Step 4/6] Saving sample files...")
        self.save_sample_response(today_data, 'sample_hockey_response.json')

        print("\n[Step 5/6] Fetching historical week...")
        historical = self.get_historical_week()

        if historical and len(historical) > 0:
            self.save_sample_response(historical[0]['data'], 'sample_hockey_historical.json')

            summary = {
                'total_days': len(historical),
                'date_range': f"{historical[-1]['date']} to {historical[0]['date']}",
                'total_games': sum(d['game_count'] for d in historical),
                'daily_breakdown': [
                    {'date': d['date'], 'games': d['game_count']}
                    for d in historical
                ]
            }
            self.save_sample_response(summary, 'historical_summary.json')

        print("\n[Step 6/6] Analyzing event stages...")
        if historical:
            stage_ids = self.analyze_event_stage_ids(historical)

        print("\n" + "=" * 60)
        print("EXPLORATION COMPLETE")
        print("=" * 60)
        print(f"\nFiles created in '{self.data_dir}':")
        print("  ✓ sample_hockey_response.json")
        print("  ✓ sample_hockey_historical.json")
        print("  ✓ historical_summary.json")

        if historical:
            print(f"\nData summary:")
            print(f"  • {len(historical)} days of data")
            print(f"  • {sum(d['game_count'] for d in historical)} total games")
            print(f"  • Date range: {historical[-1]['date']} to {historical[0]['date']}")

        print("\n✓ Next step: Run 'python exploration/analyze_structure.py'")

        return True

def main():
    explorer = SportDBExplorer()
    success = explorer.run_full_exploration()
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())
