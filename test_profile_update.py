#!/usr/bin/env python3
"""
Test script for Profile and Profile Picture Endpoints

This script demonstrates how to use the enhanced profile API endpoints
including the dedicated profile picture upload and removal endpoints.

Usage:
    python test_profile_update.py
"""

import requests
import json


def test_profile_endpoints():
    """Test all profile-related functionality"""

    # API endpoints
    base_url = "http://localhost:8000"
    profile_url = f"{base_url}/api/profile/"
    picture_upload_url = f"{base_url}/api/profile/picture/"
    picture_remove_url = f"{base_url}/api/profile/picture/remove/"

    # You'll need to replace this with a valid JWT token
    token = "your_jwt_token_here"

    headers = {"Authorization": f"Bearer {token}"}

    print("🧪 Testing Profile & Profile Picture Endpoints")
    print("=" * 60)

    # Test 1: Get current profile
    print("\n1️⃣ Getting current profile...")
    try:
        response = requests.get(profile_url, headers=headers)
        if response.status_code == 200:
            profile_data = response.json()
            print("✅ Current profile retrieved successfully:")
            print(json.dumps(profile_data, indent=2))
        else:
            print(f"❌ Failed to get profile: {response.status_code}")
            return
    except Exception as e:
        print(f"❌ Error getting profile: {e}")
        return

    # Test 2: Update profile information (without picture)
    print("\n2️⃣ Updating profile information...")

    update_data = {
        "first_name": "Updated John",
        "last_name": "Updated Doe",
        "hostel": "hall_5",
    }

    try:
        response = requests.put(
            profile_url, headers=headers, json=update_data  # Use json for non-file data
        )

        if response.status_code == 200:
            updated_profile = response.json()
            print("✅ Profile updated successfully:")
            print(json.dumps(updated_profile, indent=2))
        else:
            print(f"❌ Failed to update profile: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"❌ Error updating profile: {e}")

    # Test 3: Upload profile picture
    print("\n3️⃣ Profile picture upload test:")
    print("📝 To test profile picture upload, use the following curl command:")
    print(
        f"""
curl -X POST \\
  {picture_upload_url} \\
  -H "Authorization: Bearer {token}" \\
  -H "Content-Type: multipart/form-data" \\
  -F "profile_picture=@/path/to/your/image.jpg"
    """
    )

    # Test 4: Remove profile picture
    print("\n4️⃣ Profile picture removal test:")
    print("📝 To test profile picture removal, use the following curl command:")
    print(
        f"""
curl -X DELETE \\
  {picture_remove_url} \\
  -H "Authorization: Bearer {token}"
    """
    )

    # Test 5: Invalid hostel validation
    print("\n5️⃣ Testing validation with invalid hostel...")

    invalid_data = {"hostel": "invalid_hall"}

    try:
        response = requests.put(profile_url, headers=headers, json=invalid_data)

        if response.status_code == 400:
            error_data = response.json()
            print("✅ Validation working correctly:")
            print(json.dumps(error_data, indent=2))
        else:
            print(f"❌ Expected validation error, got: {response.status_code}")
    except Exception as e:
        print(f"❌ Error testing validation: {e}")


def show_api_documentation():
    """Show comprehensive API endpoint documentation"""

    print("\n📚 Profile & Profile Picture API Documentation")
    print("=" * 60)

    print(
        """
🔗 Profile Information Endpoints:

1️⃣ GET /api/profile/
   🔐 Authentication: Required (Bearer Token)
   📝 Description: Get user profile details
   
   ✅ Response (200):
   {
     "id": 1,
     "user_name": "johndoe",
     "email": "john@example.com",
     "first_name": "John",
     "last_name": "Doe",
     "hostel": "hall_3",
     "profile_picture": "http://localhost:8000/media/profile_pictures/image.jpg",
     "start_date": "2025-01-01T00:00:00Z",
     "is_vendor": false,
     "vendor_info": null
   }

2️⃣ PUT /api/profile/
   🔐 Authentication: Required (Bearer Token)
   📝 Content-Type: application/json
   📋 Description: Update profile info (name, hostel only)
   
   📥 Request Body:
   {
     "first_name": "Updated John",
     "last_name": "Updated Doe",
     "hostel": "hall_5"
   }
   
   ✅ Response (200):
   {
     "message": "Profile updated successfully",
     "profile": { ...updated profile data... }
   }

🖼️ Profile Picture Endpoints:

3️⃣ POST /api/profile/picture/
   🔐 Authentication: Required (Bearer Token)
   📝 Content-Type: multipart/form-data
   📋 Description: Upload/update profile picture
   
   📥 Form Data:
   - profile_picture: [image file] (max 5MB, JPG/PNG/GIF)
   
   ✅ Response (200):
   {
     "message": "Profile picture uploaded successfully",
     "profile_picture_url": "http://localhost:8000/media/profile_pictures/new_image.jpg",
     "profile": { ...updated profile data... }
   }
   
   ❌ Error Response (400):
   {
     "profile_picture": ["Profile picture file size cannot exceed 5MB."]
   }

4️⃣ DELETE /api/profile/picture/remove/
   🔐 Authentication: Required (Bearer Token)
   📋 Description: Remove current profile picture
   
   ✅ Response (200):
   {
     "message": "Profile picture removed successfully",
     "profile": { ...updated profile data... }
   }
   
   ❌ Error Response (404):
   {
     "message": "No profile picture to remove"
   }

📋 Available Hostel Options:
├── hall_1 - Hall 1
├── hall_2 - Hall 2  
├── hall_3 - Hall 3
├── hall_4 - Hall 4
├── hall_5 - Hall 5
├── hall_6 - Hall 6
├── hall_7 - Hall 7
└── hall_8 - Hall 8

🛡️ Validation Rules:
├── Profile Picture: Max 5MB, JPG/PNG/GIF only
├── Hostel: Must be valid hall choice (hall_1 to hall_8)
├── Names: Optional string fields
└── Authentication: Required for all endpoints
    """
    )


def show_usage_examples():
    """Show practical usage examples"""

    print("\n💡 Practical Usage Examples")
    print("=" * 40)

    print(
        """
🔄 Complete Profile Update Workflow:

1. Update personal information:
   curl -X PUT http://localhost:8000/api/profile/ \\
     -H "Authorization: Bearer <token>" \\
     -H "Content-Type: application/json" \\
     -d '{"first_name": "John", "last_name": "Doe", "hostel": "hall_3"}'

2. Upload profile picture:
   curl -X POST http://localhost:8000/api/profile/picture/ \\
     -H "Authorization: Bearer <token>" \\
     -F "profile_picture=@profile.jpg"

3. Check updated profile:
   curl -X GET http://localhost:8000/api/profile/ \\
     -H "Authorization: Bearer <token>"

4. Remove profile picture (if needed):
   curl -X DELETE http://localhost:8000/api/profile/picture/remove/ \\
     -H "Authorization: Bearer <token>"

📱 Frontend Integration Tips:
├── Use separate forms for profile info vs. picture upload
├── Show image preview before upload
├── Display file size/format requirements
├── Handle validation errors gracefully
└── Provide option to remove picture
    """
    )


if __name__ == "__main__":
    print("🏥 VendorXpert Profile Management Test Suite")
    print("=" * 50)

    print("\n⚠️  Before running tests:")
    print("1. Make sure Django server is running on localhost:8000")
    print("2. Replace 'your_jwt_token_here' with a valid JWT token")
    print("3. Install required dependencies: pip install requests")

    show_api_documentation()
    show_usage_examples()

    # Uncomment the line below to run actual tests
    # test_profile_endpoints()

    print("\n🎉 Enhanced profile management with dedicated picture endpoints is ready!")
