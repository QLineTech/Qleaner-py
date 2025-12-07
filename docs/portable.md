# ✅ **Goal**

You want:

* A Flask web application
* Packaged as a **macOS .app** application
* Double-click → starts your Flask server → opens window automatically
* Fully **portable** (includes its own Python runtime, dependencies, and assets)

---

# 🚀 **Best Working Solution: PyInstaller + Automator Wrapper (or Platypus)**

macOS apps require a `.app` bundle structure. Python apps don’t natively generate this, so we wrap a Flask server inside a macOS application.

Below is the **exact working method** used in real macOS desktop apps that embed local servers.

---

# 🛠️ **STEP 1 — Create a launcher script (start your Flask app & open the browser)**

Create: `run_app.sh`

```bash
#!/bin/bash

# Resolve the .app Resources directory
DIR="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$DIR/../Resources"

# Activate runtime environment
export PYTHONPATH="$APPDIR"
export FLASK_APP="$APPDIR/app.py"

# Start Flask server in background
"$APPDIR/python3" "$APPDIR/app.py" &

# Wait server
sleep 2

# Open the panel in browser (or use a WebView wrapper)
open "http://127.0.0.1:5000"
```

Make executable:

```bash
chmod +x run_app.sh
```

---

# 🛠️ **STEP 2 — Freeze Flask server using PyInstaller**

Install PyInstaller:

```bash
pip install pyinstaller
```

Build your Flask app:

```bash
pyinstaller --onefile --add-data "templates:templates" --add-data "static:static" app.py
```

This produces `dist/app`.

Rename it to `python3` (so the launcher can call it):

```bash
mv dist/app dist/python3
```

---

# 🛠️ **STEP 3 — Prepare the .app bundle layout**

You must create:

```
MyPanel.app
└── Contents
    ├── Info.plist
    ├── MacOS
    │   └── run_app.sh
    └── Resources
        ├── python3
        ├── app.py
        ├── templates/
        └── static/
```

### Make folders:

```bash
mkdir -p MyPanel.app/Contents/MacOS
mkdir -p MyPanel.app/Contents/Resources
```

Copy files:

```bash
cp run_app.sh MyPanel.app/Contents/MacOS/
cp dist/python3 MyPanel.app/Contents/Resources/
cp -R templates MyPanel.app/Contents/Resources/
cp -R static MyPanel.app/Contents/Resources/
cp app.py MyPanel.app/Contents/Resources/
```

---

# 🛠️ **STEP 4 — Create `Info.plist`**

Create: `MyPanel.app/Contents/Info.plist`

```xml
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
```

---

# 🛠️ **STEP 5 — Make the runner executable**

```bash
chmod +x MyPanel.app/Contents/MacOS/run_app.sh
chmod +x MyPanel.app/Contents/Resources/python3
```

---

# 🧪 TEST — Run like a native macOS app

Double-click:

👉 `MyPanel.app`
Your panel opens automatically in Safari/Chrome.

---

# 🟢 **This app is now fully portable**

You can zip and share:

* **No Python required**
* Flask server self-contained
* Runs even on clean macOS machines
* Can live on USB or Applications folder

---

# 🍏 OPTIONAL — Make it look like a real macOS app

Add icon: `MyPanel.icns`

Place it:

```
MyPanel.app/Contents/Resources/MyPanel.icns
```

Add to plist:

```xml
<key>CFBundleIconFile</key>
<string>MyPanel.icns</string>
```

---

# ⭐ BONUS: Wrap it with a real window (no browser!)

Use **PyWebView** for a native macOS window:

```python
import webview
import threading
from app import app

def run_flask():
    app.run()

if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    webview.create_window("Swivel Panel", "http://127.0.0.1:5000")
    webview.start()
```

Then build with PyInstaller:

```bash
pyinstaller --onefile ui.py
```

This creates a real desktop application with WebView (no external browser).
