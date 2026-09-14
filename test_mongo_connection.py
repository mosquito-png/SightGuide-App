#!/usr/bin/env python3
"""
Diagnostic script to test MongoDB Atlas connection end-to-end
"""
import sys
import os
import socket
from urllib.parse import urlparse


def main() -> None:
    try:
        import dns.resolver
        import dns.rdatatype
    except ImportError:
        pass

    print("=" * 70)
    print("MONGODB ATLAS CONNECTION DIAGNOSTIC")
    print("=" * 70)

    # Step 1: Load and parse MONGODB_URI
    print("\n[1] MONGODB_URI Configuration")
    print("-" * 70)

    from dotenv import load_dotenv
    load_dotenv()

    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("[ERROR] MONGO_URI not found in .env")
        sys.exit(1)

    # Parse the URI without exposing credentials
    parsed = urlparse(mongo_uri)
    print(f"[OK] MONGO_URI loaded")
    print(f"  Scheme: {parsed.scheme}")
    print(f"  Hostname: {parsed.hostname}")
    print(f"  Port: {parsed.port}")
    print(f"  Database: {parsed.path or '(default)'}")
    print(f"  User: {parsed.username if parsed.username else '(none)'}")

    # Step 2: DNS/SRV Resolution
    print("\n[2] DNS/SRV Record Resolution")
    print("-" * 70)

    hostname = parsed.hostname
    if not hostname:
        print("[ERROR] Could not extract hostname from MONGO_URI")
        sys.exit(1)

    # Test A record
    print(f"Testing A record resolution for: {hostname}")
    try:
        import dns.resolver
        a_records = dns.resolver.resolve(hostname, 'A')
        print(f"[OK] A record resolved to: {[str(rr) for rr in a_records]}")
    except Exception as e:
        print(f"[ERROR] A record resolution failed: {type(e).__name__}: {e}")

    # Test SRV record
    print(f"\nTesting SRV record resolution for: _mongodb._tcp.{hostname}")
    try:
        import dns.resolver
        srv_records = dns.resolver.resolve(f"_mongodb._tcp.{hostname}", 'SRV')
        print(f"[OK] SRV records resolved:")
        for rr in srv_records:
            print(f"    - {rr.target}:{rr.port} (priority: {rr.priority}, weight: {rr.weight})")
    except Exception as e:
        print(f"[ERROR] SRV record resolution failed: {type(e).__name__}: {e}")

    # Step 3: Network Connectivity
    print("\n[3] Network Connectivity to MongoDB Atlas")
    print("-" * 70)

    # Try to connect to the resolved shards
    try:
        import dns.resolver
        srv_records = dns.resolver.resolve(f"_mongodb._tcp.{hostname}", 'SRV')
        shards = [str(rr.target).rstrip('.') for rr in srv_records]

        for i, shard in enumerate(shards[:2], 1):  # Test first 2 shards
            try:
                print(f"Testing TCP connection to {shard}:27017...")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                result = sock.connect_ex((shard, 27017))
                sock.close()

                if result == 0:
                    print(f"  [OK] Connection successful")
                else:
                    print(f"  [ERROR] Connection refused (error code: {result})")
                    if result == 11001:
                        print(f"    -> Network unreachable")
                    elif result == 10061:
                        print(f"    -> Connection refused (port closed or firewall blocking)")
            except socket.gaierror as e:
                print(f"  [ERROR] DNS resolution failed: {e}")
            except socket.timeout:
                print(f"  [ERROR] Connection timeout (firewall or network latency)")
            except Exception as e:
                print(f"  [ERROR] Error: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"[ERROR] Could not retrieve SRV records: {e}")

    # Step 4: Test with PyMongo
    print("\n[4] PyMongo Connection Test")
    print("-" * 70)

    try:
        from pymongo import MongoClient
        from pymongo.errors import ServerSelectionTimeoutError, OperationFailure

        print("Attempting to connect with PyMongo...")

        # Create client with timeout
        client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)

        # Try to get server info
        try:
            info = client.server_info()
            print(f"[OK] Successfully connected to MongoDB")
            print(f"  Server version: {info.get('version', 'unknown')}")
        except ServerSelectionTimeoutError as e:
            print(f"[ERROR] Server selection timeout: {e}")
            print(f"  This usually means:")
            print(f"    1. Network connectivity issue (firewall/IP allowlist)")
            print(f"    2. MongoDB service not running")
            print(f"    3. Incorrect connection string")
        except OperationFailure as e:
            print(f"[ERROR] Authentication failed: {e}")
            print(f"  This usually means:")
            print(f"    1. Incorrect username or password")
            print(f"    2. User doesn't have permission to access this database")
        except Exception as e:
            print(f"[ERROR] Connection failed: {type(e).__name__}: {e}")
        finally:
            client.close()

    except ImportError:
        print("[WARN] PyMongo not installed - skipping PyMongo test")
    except Exception as e:
        print(f"[ERROR] Error: {type(e).__name__}: {e}")

    print("\n" + "=" * 70)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()

