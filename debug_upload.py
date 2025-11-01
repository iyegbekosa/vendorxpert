#!/usr/bin/env python3
"""
Profile Picture Upload Debugging Script

This script helps debug the "submitted data was not a file" error
by testing different upload scenarios and showing what works.
"""

import requests
import io
from PIL import Image


def create_test_image():
    """Create a simple test image in memory"""
    # Create a simple 100x100 red square image
    img = Image.new("RGB", (100, 100), color="red")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="JPEG")
    img_bytes.seek(0)
    return img_bytes


def test_upload_scenarios():
    """Test different upload scenarios to debug the issue"""

    base_url = "http://localhost:8000"
    upload_url = f"{base_url}/api/profile/picture/"

    # Replace with your actual token
    token = "your_jwt_token_here"
    headers = {"Authorization": f"Bearer {token}"}

    print("🔍 Debugging Profile Picture Upload Issues")
    print("=" * 60)

    # Test 1: Correct multipart/form-data with 'picture' field
    print("\n1️⃣ Testing with 'picture' field (multipart/form-data)")
    try:
        test_image = create_test_image()
        files = {"picture": ("test.jpg", test_image, "image/jpeg")}

        print(f"Request URL: {upload_url}")
        print(f"Headers: {headers}")
        print(f"Files: {files.keys()}")

        response = requests.post(upload_url, headers=headers, files=files)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

    except Exception as e:
        print(f"Error: {e}")

    # Test 2: Correct multipart/form-data with 'profile_picture' field
    print("\n2️⃣ Testing with 'profile_picture' field (multipart/form-data)")
    try:
        test_image = create_test_image()
        files = {"profile_picture": ("test.jpg", test_image, "image/jpeg")}

        response = requests.post(upload_url, headers=headers, files=files)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

    except Exception as e:
        print(f"Error: {e}")

    # Test 3: Wrong - JSON data (this should fail)
    print("\n3️⃣ Testing with JSON data (should fail)")
    try:
        json_data = {"picture": "not_a_file"}
        headers_json = {**headers, "Content-Type": "application/json"}

        response = requests.post(upload_url, headers=headers_json, json=json_data)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")
        print("^ This should fail with 'not a file' error")

    except Exception as e:
        print(f"Error: {e}")


def show_frontend_examples():
    """Show correct frontend implementation examples"""

    print("\n📱 Frontend Implementation Examples")
    print("=" * 50)

    print(
        """
✅ Correct JavaScript/Frontend Implementation:

1. Using FormData (RECOMMENDED):
```javascript
const formData = new FormData();
formData.append('picture', imageFile);  // or 'profile_picture'

fetch('/api/profile/picture/', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer ' + token,
    // DON'T set Content-Type header - let browser set it
  },
  body: formData
});
```

2. Using Axios:
```javascript
const formData = new FormData();
formData.append('picture', imageFile);

axios.post('/api/profile/picture/', formData, {
  headers: {
    'Authorization': 'Bearer ' + token,
    'Content-Type': 'multipart/form-data'
  }
});
```

❌ Common Mistakes:

1. Setting wrong Content-Type:
```javascript
// DON'T do this for file uploads
headers: {
  'Content-Type': 'application/json'  // ❌ Wrong for files
}
```

2. Sending file as JSON:
```javascript
// DON'T do this
const data = {
  picture: imageFile  // ❌ Won't work
};
fetch(url, {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(data)  // ❌ Can't stringify files
});
```

🔧 Debugging Checklist:
├── ✅ Request Content-Type is 'multipart/form-data'
├── ✅ File field name is 'picture' or 'profile_picture'  
├── ✅ Authorization header is included
├── ✅ File object is actual File/Blob, not string
└── ✅ No manual Content-Type header when using FormData
    """
    )


def show_curl_examples():
    """Show working curl examples"""

    print("\n🔧 Working cURL Examples")
    print("=" * 30)

    print(
        """
1. With 'picture' field name:
curl -X POST http://localhost:8000/api/profile/picture/ \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -F "picture=@/path/to/image.jpg"

2. With 'profile_picture' field name:  
curl -X POST http://localhost:8000/api/profile/picture/ \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -F "profile_picture=@/path/to/image.jpg"

Note: The -F flag automatically sets Content-Type to multipart/form-data
    """
    )


if __name__ == "__main__":
    print("🏥 VendorXprt Profile Picture Upload Debugger")
    print("=" * 50)

    print("\n⚠️  Before running tests:")
    print("1. Replace 'your_jwt_token_here' with valid token")
    print("2. Make sure Django server is running")
    print("3. Install PIL: pip install Pillow")

    show_frontend_examples()
    show_curl_examples()

    # Uncomment to run actual tests
    # test_upload_scenarios()

    print("\n🎯 Key Points:")
    print("- Use multipart/form-data, not JSON")
    print("- Field name can be 'picture' or 'profile_picture'")
    print("- Don't manually set Content-Type with FormData")
    print("- Check server logs for debug output")
