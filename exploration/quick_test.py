"""
Quick test of SportDB API connection
Run this first to verify API access
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import requests
import json
from config.config import Config

def quick_test():
    """Quick test of API connectivity"""

    print("=" * 60)
    print("QUICK API CONNECTION TEST")
    print("=" * 60)

    # Validate config
    try:
        Config.validate()
        print("\n✓ Configuration loaded successfully")
    except ValueError as e:
        print(f"\n✗ Configuration error: {e}")
        return False

    api_key = Config.SPORTDB_API_KEY
    base_url = Config.SPORTDB_BASE_URL
    url = f"{base_url}/api/flashscore/hockey/live"

    headers = {'X-API-Key': api_key}

    # Test 1: Today's games
    print("\n" + "-" * 60)
    print("Test 1: Fetching today's hockey games")
    print("-" * 60)

    try:
        response = requests.get(url, headers=headers, params={'offset': 0}, timeout=10)
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            output_file = os.path.join(Config.DATA_DIR, 'quick_test_today.json')
            with open(output_file, 'w') as f:
                json.dump(data, f, indent=2)

            print(f"✓ Success!")
            print(f"Response type: {type(data)}")

            if isinstance(data, dict):
                print(f"Top-level keys: {list(data.keys())}")
                if 'events' in data:
                    print(f"Number of events: {len(data['events'])}")
                elif 'games' in data:
                    print(f"Number of games: {len(data['games'])}")
            elif isinstance(data, list):
                print(f"List length: {len(data)}")

            print(f"\n✓ Saved to: {output_file}")
            print("\nFirst 500 characters:")
            print(json.dumps(data, indent=2)[:500])
            print("...")

        else:
            print(f"✗ Error: {response.status_code}")
            print(f"Response: {response.text}")
            return False

    except Exception as e:
        print(f"✗ Exception: {e}")
        return False

    # Test 2: Yesterday's games
    print("\n" + "-" * 60)
    print("Test 2: Fetching yesterday's hockey games")
    print("-" * 60)

    try:
        response = requests.get(url, headers=headers, params={'offset': -1}, timeout=10)
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            output_file = os.path.join(Config.DATA_DIR, 'quick_test_yesterday.json')
            with open(output_file, 'w') as f:
                json.dump(data, f, indent=2)

            print(f"✓ Success!")
            print(f"Response type: {type(data)}")

            if isinstance(data, dict):
                print(f"Top-level keys: {list(data.keys())}")
                if 'events' in data:
                    print(f"Number of events: {len(data['events'])}")
                elif 'games' in data:
                    print(f"Number of games: {len(data['games'])}")

            print(f"\n✓ Saved to: {output_file}")

        else:
            print(f"✗ Error: {response.status_code}")
            print(f"Response: {response.text}")
            return False

    except Exception as e:
        print(f"✗ Exception: {e}")
        return False

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print("\n✓ All tests passed!")
    print(f"\nFiles created in '{Config.DATA_DIR}':")
    print("  - quick_test_today.json")
    print("  - quick_test_yesterday.json")
    print("\nNext step: Run 'python exploration/explore_sportdb.py'")

    return True

if __name__ == "__main__":
    success = quick_test()
    sys.exit(0 if success else 1)
