#!/usr/bin/env python3
"""
SVG Profile Picture Upload Test

This script demonstrates and tests the new SVG support for profile pictures.
"""

import requests
import io


def create_test_svg():
    """Create a simple test SVG"""
    svg_content = """<?xml version="1.0" encoding="UTF-8"?>
<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
  <circle cx="50" cy="50" r="40" fill="blue" stroke="black" stroke-width="2"/>
  <text x="50" y="55" text-anchor="middle" fill="white" font-family="Arial" font-size="12">SVG</text>
</svg>"""
    return io.BytesIO(svg_content.encode("utf-8"))


def test_svg_upload():
    """Test SVG profile picture upload"""

    base_url = "http://localhost:8000"
    upload_url = f"{base_url}/api/profile/picture/"

    # Replace with your actual token
    token = "your_jwt_token_here"
    headers = {"Authorization": f"Bearer {token}"}

    print("🎨 Testing SVG Profile Picture Upload")
    print("=" * 50)

    # Test 1: Valid SVG upload
    print("\n1️⃣ Testing valid SVG upload")
    try:
        svg_file = create_test_svg()
        files = {"picture": ("test.svg", svg_file, "image/svg+xml")}

        print(f"Request URL: {upload_url}")
        print(f"File type: SVG")
        print(f"Content-Type: image/svg+xml")

        response = requests.post(upload_url, headers=headers, files=files)
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            print("✅ SVG upload successful!")
            print(f"Profile picture URL: {data.get('profile_picture_url')}")
        else:
            print(f"❌ Upload failed: {response.text}")

    except Exception as e:
        print(f"❌ Error: {e}")

    # Test 2: Invalid SVG (should fail)
    print("\n2️⃣ Testing invalid SVG content")
    try:
        fake_svg = io.BytesIO(b"<html>This is not SVG</html>")
        files = {"picture": ("fake.svg", fake_svg, "image/svg+xml")}

        response = requests.post(upload_url, headers=headers, files=files)
        print(f"Status Code: {response.status_code}")

        if response.status_code == 400:
            print("✅ Validation working - invalid SVG rejected")
            print(f"Error: {response.text}")
        else:
            print("❌ Should have failed validation")

    except Exception as e:
        print(f"Error: {e}")


def show_svg_examples():
    """Show SVG usage examples"""

    print("\n🎨 SVG Profile Picture Support")
    print("=" * 40)

    print(
        """
✅ New Supported Formats:
├── JPG/JPEG - Raster images
├── PNG - Raster images with transparency  
├── GIF - Animated images
└── SVG - Vector graphics (NEW!)

🖼️ SVG Benefits:
├── Scalable without quality loss
├── Small file sizes for simple graphics
├── Perfect for logos and icons
└── Crisp on all screen resolutions

📝 Frontend Usage (unchanged):
```javascript
// Works with SVG files too!
const formData = new FormData();
formData.append('picture', svgFile);

fetch('/api/profile/picture/', {
  method: 'POST', 
  headers: {'Authorization': 'Bearer ' + token},
  body: formData
});
```

🔧 cURL Example:
```bash
curl -X POST http://localhost:8000/api/profile/picture/ \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -F "picture=@avatar.svg"
```

🛡️ SVG Validation:
├── File size limit: 5MB
├── File extension: .svg
├── Content validation: Must contain <svg> tags
└── Basic security: Checks for valid SVG structure

⚠️ Security Note:
SVG files are validated for basic structure but may contain scripts.
Consider additional sanitization for production use.
    """
    )


def show_sample_svg():
    """Show a sample SVG that can be used for testing"""

    print("\n📝 Sample SVG for Testing")
    print("=" * 30)

    print(
        """
Save this as 'test-avatar.svg':

```svg
<?xml version="1.0" encoding="UTF-8"?>
<svg width="100" height="100" xmlns="http://www.w3.org/2000/svg">
  <!-- Background circle -->
  <circle cx="50" cy="50" r="48" fill="#4A90E2" stroke="#2E5C8A" stroke-width="2"/>
  
  <!-- Avatar icon -->
  <circle cx="50" cy="40" r="15" fill="white"/>
  <path d="M 25 75 Q 25 60 50 60 Q 75 60 75 75" fill="white"/>
  
  <!-- Optional text -->
  <text x="50" y="90" text-anchor="middle" fill="white" font-family="Arial" font-size="8">USER</text>
</svg>
```

Then test with:
curl -X POST http://localhost:8000/api/profile/picture/ \\
  -H "Authorization: Bearer YOUR_TOKEN" \\
  -F "picture=@test-avatar.svg"
    """
    )


if __name__ == "__main__":
    print("🏥 VendorXpert SVG Profile Picture Support")
    print("=" * 50)

    print("\n⚠️  Before testing:")
    print("1. Replace 'your_jwt_token_here' with valid token")
    print("2. Make sure Django server is running")
    print("3. Install requests: pip install requests")

    show_svg_examples()
    show_sample_svg()

    # Uncomment to run actual tests
    # test_svg_upload()

    print("\n🎉 SVG support has been added to profile pictures!")
    print("   Users can now upload vector graphics as avatars")
