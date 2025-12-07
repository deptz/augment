#!/usr/bin/env python3
"""
Simple utility to generate password hashes for API authentication.
"""

import hashlib
import getpass
import sys

def hash_password(password: str) -> str:
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def main():
    print("🔐 Password Hash Generator for Augment API")
    print("=" * 60)
    
    try:
        # Get password from user (hidden input)
        password = getpass.getpass("Enter password: ")
        
        if not password:
            print("❌ Password cannot be empty!")
            sys.exit(1)
        
        # Confirm password
        confirm_password = getpass.getpass("Confirm password: ")
        
        if password != confirm_password:
            print("❌ Passwords do not match!")
            sys.exit(1)
        
        # Generate hash
        password_hash = hash_password(password)
        
        print("\n✅ Password hash generated successfully!")
        print("-" * 40)
        print(f"Password Hash: {password_hash}")
        print("-" * 40)
        
        print("\n📝 Configuration Instructions:")
        print("1. Set the following environment variables:")
        print(f"   export AUTH_ENABLED=true")
        print(f"   export AUTH_USERNAME=admin")
        print(f"   export AUTH_PASSWORD_HASH={password_hash}")
        print("\n2. Or update your config.yaml file:")
        print("   auth:")
        print("     enabled: true")
        print("     username: admin")
        print(f"     password_hash: {password_hash}")
        
        print("\n🚀 Restart your API server to apply authentication!")
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Operation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
