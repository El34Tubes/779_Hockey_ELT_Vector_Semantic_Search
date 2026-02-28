#!/usr/bin/env python3
"""
Cleanup Oracle Text Indexes in Bronze Schema
Drops all DR$IDX* indexes that are not needed for the semantic search pipeline
"""

import oracledb
import sys
sys.path.insert(0, '/Users/johnlacroix/Desktop/BU/779 advanced database management /Term Project /nhl-semantic-analytics')
from config.db_connect import get_connection

def get_oracle_text_indexes(conn):
    """Find all Oracle Text indexes in the schema"""
    cursor = conn.cursor()

    # Query for Oracle Text indexes (CTXSYS.CONTEXT type)
    cursor.execute("""
        SELECT index_name, table_name, column_name
        FROM user_ind_columns
        WHERE index_name LIKE 'IDX_%'
          AND index_name IN (
              SELECT index_name
              FROM user_indexes
              WHERE index_type = 'DOMAIN'
          )
        ORDER BY index_name
    """)

    indexes = cursor.fetchall()
    cursor.close()
    return indexes

def count_dr_tables(conn):
    """Count DR$IDX* tables before cleanup"""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*)
        FROM user_tables
        WHERE table_name LIKE 'DR$IDX%'
    """)
    count = cursor.fetchone()[0]
    cursor.close()
    return count

def drop_oracle_text_index(conn, index_name):
    """Drop an Oracle Text index (automatically removes DR$IDX* tables)"""
    cursor = conn.cursor()
    try:
        print(f"  Dropping index: {index_name}...", end=" ")
        cursor.execute(f"DROP INDEX {index_name}")
        print("✓ Dropped")
        return True
    except oracledb.DatabaseError as e:
        print(f"✗ Error: {e}")
        return False
    finally:
        cursor.close()

def main(schema='bronze_2'):
    print("=" * 80)
    print(f"ORACLE TEXT INDEX CLEANUP - {schema.upper()}")
    print("=" * 80)

    print("\n⚠️  WARNING: This will remove all Oracle Text full-text search indexes")
    print(f"   Target schema: {schema}")
    print("   These indexes are NOT used by the NHL Semantic Analytics pipeline.")
    print("   Vector search indexes (VECTOR$IDX*) in Gold schema will NOT be affected.")

    response = input("\nDo you want to continue? (yes/no): ")
    if response.lower() not in ['yes', 'y']:
        print("\n❌ Cleanup cancelled by user")
        return

    print("\n" + "-" * 80)

    # Connect to specified bronze schema
    conn = get_connection(schema)

    # Count DR$IDX* tables before
    dr_tables_before = count_dr_tables(conn)
    print(f"\n📊 Current state:")
    print(f"   DR$IDX* tables: {dr_tables_before}")

    # Find all Oracle Text indexes
    print(f"\n🔍 Finding Oracle Text indexes...")
    indexes = get_oracle_text_indexes(conn)

    if not indexes:
        print("   ✓ No Oracle Text indexes found")
        conn.close()
        return

    print(f"   Found {len(indexes)} Oracle Text index(es):")
    for idx_name, table_name, column_name in indexes:
        print(f"     • {idx_name} on {table_name}({column_name})")

    # Drop each index
    print(f"\n🗑️  Dropping Oracle Text indexes...")
    dropped = 0
    failed = 0

    for idx_name, table_name, column_name in indexes:
        if drop_oracle_text_index(conn, idx_name):
            dropped += 1
        else:
            failed += 1

    # Commit changes
    conn.commit()

    # Count DR$IDX* tables after
    dr_tables_after = count_dr_tables(conn)

    # Summary
    print("\n" + "=" * 80)
    print("CLEANUP SUMMARY")
    print("=" * 80)
    print(f"\n✅ Indexes dropped: {dropped}")
    if failed > 0:
        print(f"❌ Failed: {failed}")
    print(f"\n📊 DR$IDX* tables:")
    print(f"   Before: {dr_tables_before}")
    print(f"   After:  {dr_tables_after}")
    print(f"   Removed: {dr_tables_before - dr_tables_after}")

    if dr_tables_after == 0:
        print("\n🎉 All Oracle Text indexes successfully removed!")
    else:
        print(f"\n⚠️  {dr_tables_after} DR$IDX* tables still remain")
        print("   Run this query to investigate:")
        print("   SELECT table_name FROM user_tables WHERE table_name LIKE 'DR$IDX%';")

    # Verify remaining tables
    cursor = conn.cursor()
    cursor.execute("""
        SELECT table_name
        FROM user_tables
        WHERE table_name NOT LIKE 'DR$IDX%'
        ORDER BY table_name
    """)
    remaining = [row[0] for row in cursor.fetchall()]
    cursor.close()

    print(f"\n📋 Remaining bronze tables ({len(remaining)}):")
    for table in remaining:
        print(f"   • {table}")

    conn.close()

    print("\n" + "=" * 80)
    print("Cleanup complete!")
    print("=" * 80)

if __name__ == "__main__":
    import sys
    schema = sys.argv[1] if len(sys.argv) > 1 else 'bronze_2'
    main(schema)
