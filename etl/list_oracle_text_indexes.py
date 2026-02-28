#!/usr/bin/env python3
"""
List Oracle Text Indexes in Bronze Schema (Dry Run)
Shows what would be dropped without actually dropping anything
"""

import oracledb
import sys
sys.path.insert(0, '/Users/johnlacroix/Desktop/BU/779 advanced database management /Term Project /nhl-semantic-analytics')
from config.db_connect import get_connection

def main(schema='bronze_2'):
    print("=" * 80)
    print(f"ORACLE TEXT INDEX REPORT - {schema.upper()} (Dry Run)")
    print("=" * 80)

    # Connect to specified bronze schema
    conn = get_connection(schema)
    cursor = conn.cursor()

    # Count all tables
    cursor.execute("SELECT COUNT(*) FROM user_tables")
    total_tables = cursor.fetchone()[0]

    # Count DR$IDX* tables
    cursor.execute("SELECT COUNT(*) FROM user_tables WHERE table_name LIKE 'DR$IDX%'")
    dr_tables = cursor.fetchone()[0]

    # Get DR$IDX* table details
    cursor.execute("""
        SELECT table_name
        FROM user_tables
        WHERE table_name LIKE 'DR$IDX%'
        ORDER BY table_name
    """)
    dr_table_details = cursor.fetchall()

    # Get Oracle Text indexes
    cursor.execute("""
        SELECT ui.index_name,
               ui.table_name,
               uic.column_name,
               ui.index_type,
               ui.status
        FROM user_indexes ui
        JOIN user_ind_columns uic ON ui.index_name = uic.index_name
        WHERE ui.index_type = 'DOMAIN'
          AND ui.index_name LIKE 'IDX_%'
        ORDER BY ui.index_name
    """)
    text_indexes = cursor.fetchall()

    # Display summary
    print(f"\n📊 Bronze Schema Statistics:")
    print(f"   Total tables: {total_tables}")
    print(f"   DR$IDX* tables: {dr_tables}")
    print(f"   User tables: {total_tables - dr_tables}")
    print(f"   Percentage DR$IDX*: {dr_tables/total_tables*100:.1f}%")

    # Display Oracle Text indexes
    print(f"\n🔍 Oracle Text Indexes ({len(text_indexes)}):")
    if text_indexes:
        for idx_name, table_name, column_name, idx_type, status in text_indexes:
            print(f"\n   Index: {idx_name}")
            print(f"     Table: {table_name}")
            print(f"     Column: {column_name}")
            print(f"     Type: {idx_type}")
            print(f"     Status: {status}")

            # Count associated DR$IDX* tables
            cursor.execute(f"""
                SELECT COUNT(*)
                FROM user_tables
                WHERE table_name LIKE 'DR$IDX_{idx_name}%'
                   OR table_name LIKE 'DR${idx_name}%'
            """)
            # Actually, let's just pattern match based on the base name
            # Extract base name from index (remove IDX_ prefix)
            base_name = idx_name.replace('IDX_', '')
            cursor.execute(f"""
                SELECT COUNT(*)
                FROM user_tables
                WHERE table_name LIKE 'DR$IDX_{base_name}%'
            """)
            related_tables = cursor.fetchone()[0]
            print(f"     Associated DR$IDX* tables: {related_tables}")
    else:
        print("   None found")

    # Display DR$IDX* table breakdown
    print(f"\n📋 DR$IDX* Tables Detail:")
    if dr_table_details:
        for i, (table_name,) in enumerate(dr_table_details, 1):
            print(f"   {i:>3}. {table_name}")
    else:
        print("   None found")

    # Recommendations
    print(f"\n💡 Recommendations:")
    if dr_tables > 0:
        print(f"   • You have {dr_tables} Oracle Text internal tables")
        print(f"   • These are NOT used by the semantic search pipeline")
        print(f"   • Dropping the {len(text_indexes)} Oracle Text index(es) will remove all {dr_tables} DR$IDX* tables")
        print(f"\n   To remove them, run:")
        print(f"   python3 etl/cleanup_oracle_text_indexes.py")
    else:
        print(f"   ✓ No Oracle Text indexes found - schema is clean!")

    # Show user tables
    cursor.execute("""
        SELECT table_name
        FROM user_tables
        WHERE table_name NOT LIKE 'DR$IDX%'
        ORDER BY table_name
    """)
    user_tables = [row[0] for row in cursor.fetchall()]

    print(f"\n✅ User Tables (will NOT be affected by cleanup):")
    for table in user_tables:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"   • {table:<40} ({count:,} rows)")

    cursor.close()
    conn.close()

    print("\n" + "=" * 80)

if __name__ == "__main__":
    import sys
    schema = sys.argv[1] if len(sys.argv) > 1 else 'bronze_2'
    main(schema)
