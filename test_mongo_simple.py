#!/usr/bin/env python3
"""Simple MongoDB connection test without external DNS libraries"""
import sys
import os
from urllib.parse import urlparse


def main() -> None:
    print("=" * 70)
    print("MONGODB ATLAS CONNECTION DIAGNOSTIC")
    print("=" * 70)

    # Load .env
    from dotenv import load_dotenv
    load_dotenv()

    mongo_uri = os.getenv("MONGO_URI")
    print("\n[1] Configuration Check")
    print("-" * 70)
    print(f"[OK] MONGO_URI loaded from .env")

    # Parse URI
    parsed = urlparse(mongo_uri)
    print(f"  Protocol: {parsed.scheme}")
    print(f"  Hostname: {parsed.hostname}")
    print(f"  Port: {parsed.port or '(default)'}")
    print(f"  User: {parsed.username or '(none)'}")

    # Test PyMongo connection
    print("\n[2] PyMongo Connection Test")
    print("-" * 70)

    try:
        from pymongo import MongoClient
        from pymongo.errors import ServerSelectionTimeoutError, OperationFailure

        print("Creating MongoDB client...")
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000)

        print("Attempting to connect...")
        client.server_info()

        print("[OK] Successfully connected to MongoDB!")

    except ServerSelectionTimeoutError as e:
        print(f"[ERROR] CONNECTION TIMEOUT or UNREACHABLE")
        print(f"  Error: {str(e)[:200]}")
        print(f"\n  LIKELY CAUSES:")
        print(f"    1. IP allowlist: Your current IP may not be in Atlas Network Access")
        print(f"    2. Network firewall: Firewall blocking port 27017")
        print(f"    3. DNS/SRV failure: Cannot resolve MongoDB cluster")
        print(f"    4. Credentials: Invalid username/password")

    except OperationFailure as e:
        print(f"[ERROR] AUTHENTICATION FAILED")
        print(f"  Error: {str(e)[:200]}")
        print(f"\n  LIKELY CAUSES:")
        print(f"    1. Invalid username or password in MONGO_URI")
        print(f"    2. User doesn't have permission for this database")
        print(f"    3. Wrong database name")

    except Exception as e:
        print(f"[ERROR] UNEXPECTED ERROR: {type(e).__name__}")
        print(f"  Message: {str(e)[:300]}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()

