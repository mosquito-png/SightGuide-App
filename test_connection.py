#!/usr/bin/env python3
import os
import sys
from urllib.parse import urlparse
from dotenv import load_dotenv


def main() -> None:
    try:
        from pymongo import MongoClient
        from pymongo.errors import ServerSelectionTimeoutError, OperationFailure
    except ImportError:
        print("[ERROR] PyMongo not installed. Run 'pip install pymongo'")
        sys.exit(1)

    load_dotenv()
    mongo_uri = os.getenv("MONGO_URI", "")

    print("MONGO_URI Check:")
    print(f"  Loaded: {bool(mongo_uri)}")
    if mongo_uri:
        parsed = urlparse(mongo_uri)
        print(f"  Scheme: {parsed.scheme}")
        print(f"  Host: {parsed.hostname}")

        if "cluster0" in mongo_uri:
            print("\n[OK] Using MongoDB Atlas (cluster0 detected)")
        elif "localhost" in mongo_uri or "mongo" in mongo_uri:
            print("\n[WARN] Using Local MongoDB (not Atlas)")

        print("\nAttempting connection...")
        try:
            client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000, retryWrites=False)
            client.admin.command('ping')
            print("[OK] CONNECTION SUCCESSFUL!")
            client.close()
            sys.exit(0)

        except ServerSelectionTimeoutError:
            print("[ERROR] Connection Timeout - Server unreachable")
            print("  Likely cause: IP not in allowlist or firewall blocking")
            sys.exit(1)
        except OperationFailure as e:
            print(f"[ERROR] Authentication Failed: {str(e)[:100]}")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Error: {type(e).__name__}: {str(e)[:100]}")
            sys.exit(1)
    else:
        print("[ERROR] MONGO_URI not set in .env")
        sys.exit(1)


if __name__ == "__main__":
    main()

