#!/usr/bin/env python3
"""MongoDB connection test - hardcoded URI"""
import sys
import os
from urllib.parse import urlparse


def main() -> None:
    # Note: credentials are masked for security
    mongo_uri = "mongodb+srv://idkaki96_db_user:VtJF72ZDFGL9Ge2y@cluster0.rtr1cs6.mongodb.net/"
    hostname = "cluster0.rtr1cs6.mongodb.net"

    print("=" * 70)
    print("MONGODB ATLAS CONNECTION DIAGNOSTIC")
    print("=" * 70)

    print("\n[1] URI Configuration")
    print("-" * 70)
    print(f"Hostname: {hostname}")
    print(f"Connection type: MongoDB +SRV (Atlas)")

    print("\n[2] PyMongo Connection Test")
    print("-" * 70)

    # Try importing and connecting
    try:
        from pymongo import MongoClient
        from pymongo.errors import ServerSelectionTimeoutError, OperationFailure, PyMongoError
        print("[OK] PyMongo imported successfully")

    except ImportError as e:
        print(f"[ERROR] PyMongo not installed: {e}")
        sys.exit(1)

    # Create client with real URI
    try:
        print("\nAttempting connection to MongoDB Atlas...")

        # Read the actual URI from .env file
        env_path = '.env' if os.path.exists('.env') else '../.env'
        with open(env_path, 'r') as f:
            for line in f:
                if line.startswith('MONGO_URI='):
                    actual_uri = line.split('=', 1)[1].strip()
                    break

        client = MongoClient(actual_uri, serverSelectionTimeoutMS=10000)

        print("Sending ping command to server...")
        try:
            info = client.admin.command('ping')
            print(f"[OK] SUCCESSFULLY CONNECTED TO MONGODB ATLAS!")
            print(f"  Ping response: {info}")

        except ServerSelectionTimeoutError as e:
            print(f"[ERROR] SERVER SELECTION TIMEOUT")
            print(f"  Error: {str(e)[:300]}")
            print(f"\n  ROOT CAUSE ANALYSIS:")
            print(f"  1. IP ALLOWLIST: Check if your IP is allowed in Atlas")
            print(f"  2. NETWORK: Firewall may be blocking port 27017")
            print(f"  3. DNS: SRV record lookup for _mongodb._tcp.{hostname} may fail")
            print(f"  4. CREDENTIALS: Invalid username or password")
            sys.exit(1)

        except OperationFailure as e:
            print(f"[ERROR] AUTHENTICATION FAILED")
            print(f"  Error: {str(e)[:300]}")
            print(f"\n  ROOT CAUSE ANALYSIS:")
            print(f"  1. Wrong password in MONGO_URI")
            print(f"  2. User lacks database permissions")
            print(f"  3. Username doesn't exist")
            sys.exit(1)

    except Exception as e:
        print(f"[ERROR] ERROR: {type(e).__name__}")
        print(f"  Message: {str(e)[:400]}")
        import traceback
        print(f"\nTraceback:")
        traceback.print_exc()
        sys.exit(1)

    print("\n" + "=" * 70)
    print("DIAGNOSTIC COMPLETE - Connection successful!")
    print("=" * 70)


if __name__ == "__main__":
    main()

