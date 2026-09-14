import requests
import time


def main() -> None:
    print("=" * 70)
    print("PROJECT STATUS REPORT")
    print("=" * 70)

    # Test Backend Health
    print("\n[1] BACKEND STATUS")
    print("-" * 70)
    try:
        response = requests.get("http://localhost:8000/api/health", timeout=5)
        if response.status_code == 200:
            print(f"[OK] Backend API responding")
            print(f"  Endpoint: http://localhost:8000/api/health")
            print(f"  Status: {response.status_code}")
            print(f"  Response: {response.json()}")
        else:
            print(f"[WARN] Backend returned unexpected status: {response.status_code}")
    except requests.ConnectionError:
        print(f"[ERROR] Cannot connect to backend at http://localhost:8000")
    except Exception as e:
        print(f"[ERROR] Error: {type(e).__name__}: {e}")

    # Test Frontend
    print("\n[2] FRONTEND STATUS")
    print("-" * 70)
    try:
        response = requests.get("http://localhost:5173", timeout=5)
        print(f"[OK] Frontend accessible")
        print(f"  URL: http://localhost:5173")
        print(f"  Status: {response.status_code}")
    except requests.ConnectionError:
        print(f"[WARN] Frontend not yet running")
    except Exception as e:
        print(f"[WARN] Frontend status: {type(e).__name__}")

    # Test MongoDB
    print("\n[3] MONGODB CONNECTION")
    print("-" * 70)
    try:
        from pymongo import MongoClient
        from dotenv import load_dotenv
        import os

        load_dotenv()
        uri = os.getenv("MONGO_URI")
        if not uri:
            print("[ERROR] MONGO_URI is not set in the environment. Cannot connect to MongoDB.")
        else:
            client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            client.admin.command('ping')
            print(f"[OK] MongoDB Atlas connected")
            print(f"  Cluster: cluster0.rtr1cs6.mongodb.net")
            print(f"  Database: sightguide")
            client.close()
    except Exception as e:
        print(f"[ERROR] MongoDB error: {type(e).__name__}: {str(e)[:100]}")

    # Check API endpoints
    print("\n[4] AVAILABLE API ENDPOINTS")
    print("-" * 70)
    try:
        response = requests.get("http://localhost:8000/openapi.json", timeout=5)
        if response.status_code == 200:
            api_spec = response.json()
            paths = api_spec.get("paths", {})
            print(f"[OK] Found {len(paths)} API endpoints:")
            for path in sorted(paths.keys()):
                methods = list(paths[path].keys())
                print(f"    {path}: {', '.join(methods).upper()}")
    except Exception as e:
        print(f"[WARN] Could not fetch API spec: {type(e).__name__}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()

