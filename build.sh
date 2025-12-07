#!/bin/bash

# Exit on error
set -e

APP_NAME="Qleaner"
DIST_DIR="dist"
BUILD_DIR="build"
APP_BUNDLE="${APP_NAME}.app"

echo "🚀 Starting portable build process for ${APP_NAME}..."

# 1. Clean up previous builds
echo "🧹 Cleaning up previous builds..."
rm -rf "$DIST_DIR" "$BUILD_DIR" "$APP_BUNDLE" "*.spec"

# 2. Check/Install PyInstaller
# Check if venv exists and use it
if [ -d "venv" ]; then
    echo "🐍 Found venv, activating..."
    source venv/bin/activate
fi

if ! python3 -m PyInstaller --version &> /dev/null; then
    echo "📦 PyInstaller not found. Installing..."
    python3 -m pip install pyinstaller
else
    echo "✅ PyInstaller is already installed."
fi

# 3. Build Flask app with PyInstaller
echo "🔨 Freezing Flask app..."
# Note: We don't use --add-data here because we'll copy assets manually to the bundle
# to ensure the directory structure matches what the launcher script expects.
python3 -m PyInstaller --onefile --name python3 app.py

# 4. Prepare .app bundle structure
echo "📂 Creating .app bundle structure..."
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

# 5. Create launcher script (run_app.sh)
echo "📜 Creating launcher script..."
cat > "${APP_BUNDLE}/Contents/MacOS/run_app.sh" << 'EOF'
#!/bin/bash

# Resolve the .app Resources directory
DIR="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$DIR/../Resources"

# Activate runtime environment
export PYTHONPATH="$APPDIR"
export FLASK_APP="$APPDIR/app.py"

# Start Flask server in background
# We use the bundled 'python3' binary which is actually our frozen app
"$APPDIR/python3" "$APPDIR/app.py" &
SERVER_PID=$!

# Wait for server to start
sleep 2

# Open the panel in default browser
open "http://127.0.0.1:5000"

# Optional: Wait for the server process (if you want the script to keep running)
# wait $SERVER_PID
EOF

# 6. Create Info.plist
echo "📝 Creating Info.plist..."
cat > "${APP_BUNDLE}/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" 
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Swivel Panel</string>

  <key>CFBundleIdentifier</key>
  <string>tr.com.swivel.panel</string>

  <key>CFBundleVersion</key>
  <string>1.0</string>

  <key>CFBundleExecutable</key>
  <string>run_app.sh</string>

  <key>LSBackgroundOnly</key>
  <false/>
</dict>
</plist>
EOF

# 7. Copy files to Resources
echo "cp assets..."
cp "${DIST_DIR}/python3" "${APP_BUNDLE}/Contents/Resources/"
cp -R templates "${APP_BUNDLE}/Contents/Resources/"
# Check if static exists before copying
if [ -d "static" ]; then
    cp -R static "${APP_BUNDLE}/Contents/Resources/"
fi
cp app.py "${APP_BUNDLE}/Contents/Resources/"

# 8. Make executables
echo "🔐 Setting permissions..."
chmod +x "${APP_BUNDLE}/Contents/MacOS/run_app.sh"
chmod +x "${APP_BUNDLE}/Contents/Resources/python3"

echo "✅ Build complete! You can now run ${APP_BUNDLE}"
echo "👉 To test: open ${APP_BUNDLE}"
