#!/usr/bin/env python3
"""
Q-Cleaner Web Panel for macOS
A web-based cache and temp file cleaner with system monitoring
"""

import os
import shutil
import subprocess
import json
import threading
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
from flask import Flask, render_template, jsonify, request, send_from_directory
import webbrowser
import socket

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not installed. System monitoring will be limited.")
    print("Install with: pip install psutil")

app = Flask(__name__)

# Global state
scan_results = []
scan_in_progress = False
scan_complete = False
scan_progress = {
    "current": 0,
    "total": 0,
    "percent": 0,
    "current_location": "",
    "found_count": 0,
    "total_size": 0
}


@dataclass
class CacheLocation:
    id: str
    path: str
    name: str
    description: str
    category: str
    hint: str
    impact: str
    risk: str
    size: int = 0
    size_human: str = "0B"
    selected: bool = False
    exists: bool = False


def get_home() -> str:
    return str(Path.home())


def human_readable_size(size_bytes: int) -> str:
    if size_bytes < 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if abs(size_bytes) < 1024.0:
            if unit == 'B':
                return f"{size_bytes} {unit}"
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def get_directory_size(path: str) -> int:
    try:
        result = subprocess.run(
            ['du', '-sk', path],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            size_kb = int(result.stdout.split()[0])
            return size_kb * 1024
    except:
        pass
    
    total_size = 0
    try:
        path_obj = Path(path)
        if path_obj.is_file():
            return path_obj.stat().st_size
        for entry in path_obj.rglob('*'):
            try:
                if entry.is_file():
                    total_size += entry.stat().st_size
            except:
                pass
    except:
        pass
    return total_size


def get_cache_locations() -> List[CacheLocation]:
    home = get_home()
    
    locations = [
        CacheLocation(
            id="user_caches",
            path=f"{home}/Library/Caches",
            name="User Application Caches",
            description="Cache files from all your applications",
            category="System",
            hint="This folder contains cached data from all applications you use. Apps store temporary files here to speed up loading times.",
            impact="Apps will need to re-download or regenerate their cached data. Generally safe.",
            risk="low"
        ),
        CacheLocation(
            id="system_caches",
            path="/Library/Caches",
            name="System Application Caches",
            description="System-wide application caches",
            category="System",
            hint="Contains cached data for system-level applications and services.",
            impact="System apps will regenerate caches as needed. May require admin password.",
            risk="medium"
        ),
        CacheLocation(
            id="xcode_derived",
            path=f"{home}/Library/Developer/Xcode/DerivedData",
            name="Xcode DerivedData",
            description="Xcode build intermediates and indexes",
            category="Developer",
            hint="Contains all build products, indexes, and logs from Xcode projects.",
            impact="Next build will take longer as Xcode rebuilds everything from scratch.",
            risk="low"
        ),
        CacheLocation(
            id="xcode_archives",
            path=f"{home}/Library/Developer/Xcode/Archives",
            name="Xcode Archives",
            description="App Store submission archives",
            category="Developer",
            hint="Contains archived builds used for App Store submissions.",
            impact="⚠️ You will lose the ability to symbolicate crash reports from these builds.",
            risk="high"
        ),
        CacheLocation(
            id="xcode_device_support",
            path=f"{home}/Library/Developer/Xcode/iOS DeviceSupport",
            name="iOS Device Support",
            description="Debug symbols for iOS devices",
            category="Developer",
            hint="Contains debug symbols for each iOS version you've connected. Often 2-5GB each!",
            impact="Xcode will re-download symbols when you next connect a device.",
            risk="low"
        ),
        CacheLocation(
            id="simulator_devices",
            path=f"{home}/Library/Developer/CoreSimulator/Devices",
            name="iOS Simulator Devices",
            description="All iOS Simulator instances and data",
            category="Developer",
            hint="Contains all simulator devices and their installed apps and data.",
            impact="⚠️ ALL simulator devices and their app data will be deleted.",
            risk="high"
        ),
        CacheLocation(
            id="npm_cache",
            path=f"{home}/.npm/_cacache",
            name="NPM Cache",
            description="Downloaded NPM packages cache",
            category="Packages",
            hint="NPM stores downloaded packages here to avoid re-downloading them.",
            impact="NPM will re-download packages when needed.",
            risk="low"
        ),
        CacheLocation(
            id="yarn_cache",
            path=f"{home}/.yarn/cache",
            name="Yarn Cache",
            description="Downloaded Yarn packages cache",
            category="Packages",
            hint="Yarn's offline cache of all packages.",
            impact="Yarn will need to re-download packages.",
            risk="low"
        ),
        CacheLocation(
            id="pip_cache",
            path=f"{home}/.cache/pip",
            name="Python Pip Cache",
            description="Downloaded Python packages cache",
            category="Packages",
            hint="Pip caches downloaded wheel and source packages here.",
            impact="Pip will re-download packages when installing.",
            risk="low"
        ),
        CacheLocation(
            id="pub_cache",
            path=f"{home}/.pub-cache",
            name="Flutter/Dart Pub Cache",
            description="Dart and Flutter packages",
            category="Packages",
            hint="Contains all Flutter and Dart packages.",
            impact="Run 'flutter pub get' again after cleaning.",
            risk="low"
        ),
        CacheLocation(
            id="gradle_cache",
            path=f"{home}/.gradle/caches",
            name="Gradle Cache",
            description="Android/Java build cache",
            category="Packages",
            hint="Gradle stores downloaded dependencies and build outputs here.",
            impact="Android/Gradle builds will re-download dependencies.",
            risk="low"
        ),
        CacheLocation(
            id="cocoapods",
            path=f"{home}/.cocoapods/repos",
            name="CocoaPods Repos",
            description="CocoaPods spec repositories",
            category="Packages",
            hint="Contains the CocoaPods master spec repo. Can be 1-2GB.",
            impact="Next 'pod install' will re-clone spec repos.",
            risk="low"
        ),
        CacheLocation(
            id="safari_cache",
            path=f"{home}/Library/Caches/com.apple.Safari",
            name="Safari Cache",
            description="Safari browser cache",
            category="Browsers",
            hint="Contains cached web pages, images, scripts from Safari.",
            impact="Websites will reload fresh content. Login sessions preserved.",
            risk="low"
        ),
        CacheLocation(
            id="chrome_cache",
            path=f"{home}/Library/Caches/Google/Chrome/Default/Cache",
            name="Chrome Cache",
            description="Chrome browser cache",
            category="Browsers",
            hint="Chrome's cached web content.",
            impact="Chrome will re-download web content. Cookies and history preserved.",
            risk="low"
        ),
        CacheLocation(
            id="firefox_cache",
            path=f"{home}/Library/Caches/Firefox",
            name="Firefox Cache",
            description="Firefox browser cache",
            category="Browsers",
            hint="Firefox's cached web content.",
            impact="Firefox will reload content. Login sessions safe.",
            risk="low"
        ),
        CacheLocation(
            id="vscode_cache",
            path=f"{home}/Library/Application Support/Code/CachedData",
            name="VS Code Cache",
            description="Visual Studio Code cached data",
            category="Applications",
            hint="VS Code caches extension data and workspace state.",
            impact="VS Code may take slightly longer to start.",
            risk="low"
        ),
        CacheLocation(
            id="slack_cache",
            path=f"{home}/Library/Application Support/Slack/Cache",
            name="Slack Cache",
            description="Slack cached messages and files",
            category="Applications",
            hint="Contains cached messages, files, and images from Slack.",
            impact="Slack will re-download message history and files.",
            risk="low"
        ),
        CacheLocation(
            id="discord_cache",
            path=f"{home}/Library/Application Support/discord/Cache",
            name="Discord Cache",
            description="Discord cached content",
            category="Applications",
            hint="Cached images, videos, and other media from Discord.",
            impact="Discord will re-download media from channels.",
            risk="low"
        ),
        CacheLocation(
            id="spotify_cache",
            path=f"{home}/Library/Application Support/Spotify/PersistentCache",
            name="Spotify Cache",
            description="Spotify offline music cache",
            category="Applications",
            hint="Contains cached and downloaded music for offline playback.",
            impact="⚠️ Downloaded songs for offline will be removed.",
            risk="medium"
        ),
        CacheLocation(
            id="docker_data",
            path=f"{home}/Library/Containers/com.docker.docker/Data/vms",
            name="Docker VM Data",
            description="Docker Desktop VM disk images",
            category="Docker",
            hint="Docker Desktop runs in a VM. This contains all containers and images.",
            impact="⚠️ ALL Docker images, containers, and volumes will be deleted.",
            risk="high"
        ),
        CacheLocation(
            id="tmp",
            path="/tmp",
            name="System Temp Files",
            description="Temporary files from running apps",
            category="Temp",
            hint="Standard Unix temp directory. Cleared on reboot.",
            impact="Running apps may lose temporary work. Close apps first.",
            risk="low"
        ),
        CacheLocation(
            id="user_logs",
            path=f"{home}/Library/Logs",
            name="User Application Logs",
            description="Log files from applications",
            category="Logs",
            hint="Applications store their log files here for debugging.",
            impact="Historical logs will be lost. Apps create new logs as needed.",
            risk="low"
        ),
        CacheLocation(
            id="ios_backups",
            path=f"{home}/Library/Application Support/MobileSync/Backup",
            name="iOS Device Backups",
            description="iPhone/iPad local backups",
            category="Backups",
            hint="Local backups of iOS devices. Each can be 10-100GB.",
            impact="⚠️ ALL local device backups will be permanently deleted.",
            risk="high"
        ),
        CacheLocation(
            id="homebrew_cache",
            path=f"{home}/Library/Caches/Homebrew",
            name="Homebrew Downloads",
            description="Downloaded Homebrew packages",
            category="Packages",
            hint="Homebrew caches downloaded bottles and source archives.",
            impact="Homebrew will re-download packages if reinstalled.",
            risk="low"
        ),
    ]
    
    return locations


# Routes
@app.route('/')
def index():
    return render_template('app.html')


@app.route('/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory('assets', filename)


@app.route('/api/scan', methods=['POST'])
def start_scan():
    global scan_results, scan_in_progress, scan_complete, scan_progress
    
    if scan_in_progress:
        return jsonify({"status": "already_scanning"})
    
    scan_in_progress = True
    scan_complete = False
    scan_results = []
    scan_progress = {"current": 0, "total": 0, "percent": 0, "current_location": "", "found_count": 0, "total_size": 0}
    
    def do_scan():
        global scan_results, scan_in_progress, scan_complete, scan_progress
        locations = get_cache_locations()
        results = []
        
        total_locations = len(locations)
        scan_progress["total"] = total_locations + 1
        
        for i, loc in enumerate(locations):
            scan_progress["current"] = i + 1
            scan_progress["current_location"] = loc.name
            scan_progress["percent"] = int((i / (total_locations + 1)) * 100)
            
            path = Path(loc.path)
            if path.exists():
                loc.exists = True
                loc.size = get_directory_size(loc.path)
                loc.size_human = human_readable_size(loc.size)
                if loc.size > 0:
                    loc.selected = True
                    results.append(loc)
                    scan_progress["found_count"] = len(results)
                    scan_progress["total_size"] = sum(r.size for r in results)
        
        # Scan container caches
        scan_progress["current_location"] = "Container Apps"
        home = get_home()
        containers_path = Path(f"{home}/Library/Containers")
        if containers_path.exists():
            for container in containers_path.iterdir():
                cache_path = container / "Data" / "Library" / "Caches"
                if cache_path.exists() and cache_path.is_dir():
                    app_name = container.name.split('.')[-1] if '.' in container.name else container.name
                    size = get_directory_size(str(cache_path))
                    if size > 0:
                        results.append(CacheLocation(
                            id=f"container_{app_name}",
                            path=str(cache_path),
                            name=f"{app_name} Cache",
                            description=f"Sandboxed app cache for {app_name}",
                            category="Containers",
                            hint=f"Cache data for the sandboxed app '{app_name}'.",
                            impact="The app will recreate its cache as needed.",
                            risk="low",
                            size=size,
                            size_human=human_readable_size(size),
                            selected=True,
                            exists=True
                        ))
                        scan_progress["found_count"] = len(results)
                        scan_progress["total_size"] = sum(r.size for r in results)
        
        scan_progress["percent"] = 100
        scan_progress["current_location"] = "Complete"
        
        results.sort(key=lambda x: x.size, reverse=True)
        scan_results = results
        scan_in_progress = False
        scan_complete = True
    
    thread = threading.Thread(target=do_scan)
    thread.start()
    
    return jsonify({"status": "started"})


@app.route('/api/scan/status')
def scan_status():
    return jsonify({
        "in_progress": scan_in_progress,
        "complete": scan_complete,
        "count": len(scan_results),
        "current_location": scan_progress.get("current_location", ""),
        "progress": scan_progress
    })


@app.route('/api/locations')
def get_locations():
    return jsonify([asdict(loc) for loc in scan_results])


@app.route('/api/clean', methods=['POST'])
def clean_locations():
    data = request.json
    ids_to_clean = data.get('ids', [])
    
    results = []
    for loc in scan_results:
        if loc.id in ids_to_clean:
            success = False
            message = ""
            try:
                path = Path(loc.path)
                if path.is_dir():
                    for item in path.iterdir():
                        try:
                            if item.is_dir():
                                shutil.rmtree(item)
                            else:
                                item.unlink()
                        except:
                            pass
                    success = True
                    message = "Cleaned"
                elif path.is_file():
                    path.unlink()
                    success = True
                    message = "Deleted"
            except PermissionError:
                message = "Permission denied"
            except Exception as e:
                message = str(e)
            
            results.append({
                "id": loc.id,
                "name": loc.name,
                "success": success,
                "message": message
            })
    
    return jsonify({"results": results})


# System monitoring endpoints
@app.route('/api/system/stats')
def system_stats():
    stats = {
        "cpu_percent": 0,
        "cpu_count": 0,
        "memory": {"total": 0, "used": 0, "free": 0, "percent": 0, "total_human": "N/A", "used_human": "N/A", "free_human": "N/A"},
        "disk": {"total": 0, "used": 0, "free": 0, "percent": 0, "total_human": "N/A", "used_human": "N/A", "free_human": "N/A"},
        "network": {"bytes_sent": 0, "bytes_recv": 0, "sent_human": "0 B", "recv_human": "0 B"},
        "uptime": "N/A"
    }
    
    if PSUTIL_AVAILABLE:
        stats["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        stats["cpu_count"] = psutil.cpu_count()
        
        mem = psutil.virtual_memory()
        stats["memory"] = {
            "total": mem.total,
            "used": mem.used,
            "free": mem.available,
            "percent": mem.percent,
            "total_human": human_readable_size(mem.total),
            "used_human": human_readable_size(mem.used),
            "free_human": human_readable_size(mem.available)
        }
        
        disk = psutil.disk_usage('/')
        stats["disk"] = {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
            "percent": disk.percent,
            "total_human": human_readable_size(disk.total),
            "used_human": human_readable_size(disk.used),
            "free_human": human_readable_size(disk.free)
        }
        
        net = psutil.net_io_counters()
        stats["network"] = {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "sent_human": human_readable_size(net.bytes_sent),
            "recv_human": human_readable_size(net.bytes_recv)
        }
        
        try:
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            days, remainder = divmod(int(uptime_seconds), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)
            if days > 0:
                stats["uptime"] = f"{days}d {hours}h {minutes}m"
            elif hours > 0:
                stats["uptime"] = f"{hours}h {minutes}m"
            else:
                stats["uptime"] = f"{minutes}m"
        except:
            pass
    else:
        # Fallback for disk
        try:
            result = subprocess.run(['df', '-k', '/'], capture_output=True, text=True)
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 2:
                parts = lines[1].split()
                total = int(parts[1]) * 1024
                used = int(parts[2]) * 1024
                free = int(parts[3]) * 1024
                percent = int(parts[4].replace('%', ''))
                stats["disk"] = {
                    "total": total, "used": used, "free": free, "percent": percent,
                    "total_human": human_readable_size(total),
                    "used_human": human_readable_size(used),
                    "free_human": human_readable_size(free)
                }
        except:
            pass
    
    return jsonify(stats)


@app.route('/api/system/processes')
def get_top_processes():
    processes = {"by_cpu": [], "by_memory": []}
    
    if PSUTIL_AVAILABLE:
        try:
            procs = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'memory_info']):
                try:
                    pinfo = proc.info
                    if pinfo['cpu_percent'] is not None:
                        procs.append({
                            "pid": pinfo['pid'],
                            "name": pinfo['name'],
                            "cpu_percent": round(pinfo['cpu_percent'], 1),
                            "memory_percent": round(pinfo['memory_percent'], 1) if pinfo['memory_percent'] else 0,
                            "memory": pinfo['memory_info'].rss if pinfo['memory_info'] else 0,
                            "memory_human": human_readable_size(pinfo['memory_info'].rss if pinfo['memory_info'] else 0)
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            
            processes["by_cpu"] = sorted(procs, key=lambda x: x['cpu_percent'], reverse=True)[:15]
            processes["by_memory"] = sorted(procs, key=lambda x: x['memory'], reverse=True)[:15]
        except:
            pass
    
    return jsonify(processes)


def open_browser(port):
    time.sleep(1)
    webbrowser.open(f'http://127.0.0.1:{port}')


if __name__ == '__main__':
    # Find available port
    port = 5050
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                break
            port += 1

    print("\n" + "=" * 50)
    print("  Q-Cleaner Web Panel")
    print(f"  Open http://127.0.0.1:{port} in your browser")
    print("=" * 50 + "\n")
    
    threading.Thread(target=open_browser, args=(port,), daemon=True).start()
    app.run(host='127.0.0.1', port=port, debug=False)
