# **Advanced Forensic Heuristics for the Detection of Residual Software Artifacts**

## **1\. Introduction: The Persistence of Digital Residue**

In the domain of digital forensics and systems administration, the concept of software "uninstallation" is frequently a misnomer. A fundamental disparity exists between the user’s perception of deleting an application—often visualized as the complete removal of a binary and its associated data—and the operational reality of modern operating systems. Operating systems such as Microsoft Windows, macOS, Linux, Android, and iOS function on complex architectures where applications are deeply integrated into system registries, shared libraries, user configuration profiles, and kernel-level caches. The standard uninstallation routines, typically vendor-supplied scripts or package manager instructions, are often designed with a bias toward system stability and user convenience rather than complete sanitization. Consequently, they prioritize leaving shared resources intact and preserving user customizations for potential future reinstallations.

This operational philosophy creates a significant "uninstallation gap"—a delta of residual data that persists long after the primary executable has been excised from the storage media. For the forensic investigator, this gap is a rich seam of evidence. It allows for the reconstruction of a system's history, proving the past execution of illicit software, identifying the versioning of unpatched applications, or recovering configuration data that reveals user intent. Conversely, for the privacy advocate or system optimizer, these remnants represent "digital rot," contributing to configuration drift, storage bloat, and potential privacy leaks through persistent authentication tokens.

The detection of these uninstalled applications requires moving beyond simple file enumeration. It demands a sophisticated understanding of heuristic algorithms, registry hive parsing, database journaling, and filesystem metadata analysis. This report provides an exhaustive technical analysis of the logics used to detect these artifacts across five major platforms, synthesizing the specific mechanisms of persistence and the algorithmic approaches required to identify them.

## ---

**2\. The Windows Ecosystem: Registry Forensics and Filesystem Heuristics**

The Microsoft Windows operating system presents the most intricate landscape for residual data due to its reliance on a centralized, hierarchical configuration database (the Registry) and a complex mechanism for managing shared libraries (DLLs). The detection logic for uninstalled software on Windows must generally operate in two modes: deterministic analysis of registry keys that explicitly track software installation, and probabilistic heuristic analysis of the filesystem and volatile caches.

### **2.1. Registry-Based Detection Logic**

The Windows Registry is the primary locus for configuration data. When software is uninstalled, specific keys often remain due to uninstaller errors, intentional retention of license data, or the architectural design of the Windows Installer service.

#### **2.1.1. The Uninstall Key and ARP Cache Analysis**

The most direct evidence of a program's current or past presence resides in the keys responsible for populating the "Add/Remove Programs" (ARP) interface. While a successful uninstallation should remove the subkey associated with the application, failures in the uninstaller routine often leave these keys orphaned.

**Primary Artifact Locations:**

* HKEY\_LOCAL\_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall  
* HKEY\_LOCAL\_MACHINE\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall (for 32-bit applications on 64-bit architectures).1

Detection Heuristics:  
Forensic tools and uninstaller utilities (such as Revo Uninstaller or Bulk Crap Uninstaller) employ a specific logic to validate these keys.3 The algorithm iterates through each subkey, extracting the UninstallString or InstallLocation values. It then performs a filesystem check:

1. **Path Resolution:** The algorithm parses the registry value to determine the expected installation directory (e.g., C:\\Program Files\\Vendor\\App).  
2. **Existence Check:** It queries the filesystem API to verify if the executable or the directory exists.  
3. **Orphan Flagging:** If the registry key exists but the target path is invalid or empty, the entry is flagged as a "leftover" or "orphaned" registry key. This is a deterministic indicator that the software was installed but removed imperfectly.5

#### **2.1.2. The SharedDLLs Reference Counting Mechanism**

A more sophisticated and frequent source of residue is the SharedDLLs registry key. Windows uses this mechanism to manage library dependencies and prevent the "DLL Hell" scenario where removing one application breaks another by deleting a shared library.

Mechanism of Persistence:  
The registry key HKEY\_LOCAL\_MACHINE\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\SharedDLLs contains a list of file paths (typically .dll files) mapped to an integer value, which represents the "Reference Count".6

* **Installation:** When an installer places a shared file (e.g., in System32), it checks this key. If the path exists, it increments the count (e.g., from 1 to 2). If not, it creates the entry with a count of 1\.  
* **Uninstallation:** The uninstaller decrements the count. The filesystem deletion routine is triggered *only* if the count reaches zero.7

The Failure Mode and Detection Logic:  
Orphaned entries arise when an installer fails to decrement the count or when a "legacy" installer does not interact with the key correctly, leaving a permanent non-zero count for a file that is no longer needed by any active application.8  
To detect these leftovers, forensic scripts utilize the following logic:

1. **Enumeration:** Iterate through all values in the SharedDLLs key.  
2. **File Validation:** Check if the file path referenced in the value exists on the disk.  
   * *Case A:* The file is missing, but the registry entry remains. This is a confirmed orphan registry entry.8  
   * *Case B:* The file exists. The detection logic must then cross-reference the file against the database of currently installed MSI packages (using WMI or MsiEnumProducts). If no installed product claims ownership of the DLL, yet it resides in a shared location with a high reference count, it is a candidate for orphaned data.9

| Artifact | Registry Path | Data Type | Forensic Value |
| :---- | :---- | :---- | :---- |
| **ARP Entry** | HKLM\\...\\Uninstall | String | User-visible proof of install; often retains install date/version. |
| **SharedDLLs** | HKLM\\...\\SharedDLLs | DWORD (Ref Count) | Proof of dependency usage; often retains paths to deleted libs. |
| **Services** | HKLM\\SYSTEM\\CurrentControlSet\\Services | Key Structure | Evidence of background agents; often persist after main binary deletion. |

Table 1: Registry Artifacts for Uninstalled Software 1

#### **2.1.3. Service and Driver Remnants**

Uninstalled security software, system tools, and malware frequently leave behind service configurations. The registry key HKEY\_LOCAL\_MACHINE\\SYSTEM\\CurrentControlSet\\Services defines the drivers and services loaded by the kernel.  
Detection Logic:  
Algorithms designed to clean these remnants scan for services where the ImagePath points to a non-existent file. This is a high-confidence indicator of an uninstalled application. Furthermore, the Legacy subkeys within the Enum branch often contain metadata about drivers that were loaded in previous sessions, providing a historical record even if the Service entry itself is deleted.10

### **2.2. Execution Artifacts: ShimCache and AmCache**

For the forensic analyst, proving that an application was executed (even if uninstalled) is often more critical than proving it was simply present. Windows maintains detailed execution artifacts that persist through uninstallation.

#### **2.2.1. ShimCache (AppCompatCache)**

The Application Compatibility Cache (ShimCache) is designed to identify applications that require compatibility "shims" to function on newer versions of Windows. Crucially, this cache tracks executables based on their file path and modification timestamp.

Mechanism and Persistence:  
ShimCache data resides in the kernel memory and is serialized to the registry only upon system shutdown or restart. It is located at SYSTEM\\CurrentControlSet\\Control\\Session Manager\\AppCompatCache.12

* **Forensic Significance:** Because ShimCache records the state of executables *before* they are potentially deleted by an uninstaller, it acts as a "black box" recorder. Even if C:\\Program Files\\MaliciousApp\\malware.exe is deleted by an uninstaller or a user, the ShimCache entry retains the record that the file existed and was scanned by the shim engine.  
* **Detection:** Analysts parse this registry blob to reconstruct a timeline. The presence of a file path in ShimCache that does not exist on the filesystem is definitive proof of past presence.14

#### **2.2.2. AmCache.hve**

Introduced in Windows 8, the AmCache.hve is a separate registry hive located at C:\\Windows\\AppCompat\\Programs\\Amcache.hve.12 Unlike ShimCache, AmCache provides a comprehensive inventory of executed applications that includes cryptographic hashes.

The SHA-1 Logic:  
The AmCache stores the SHA-1 hash of the executable file. This is a critical differentiator for detection.

* **Hash Persistence:** If an application is uninstalled, the AmCache.hve is rarely purged. The entry persists, allowing investigators to identify exactly which version of a program was installed.  
* **Identification:** By extracting the SHA-1 hash from the AmCache of an uninstalled program, an analyst can query threat intelligence databases (like VirusTotal) to identify the software, even if the file path was generic (e.g., setup.exe) or obfuscated.15  
* **Installation Source:** AmCache metadata often includes volume GUIDs and source indicators, revealing whether an uninstalled application was run from a local disk, a USB drive, or a network share.14

### **2.3. Filesystem Heuristics and Corpse Detection**

Beyond the registry, the NTFS filesystem accumulates residue in predictable "whitelist" locations. Heuristic scanners like Bulk Crap Uninstaller (BCU) or BleachBit utilize pattern-matching algorithms to identify these files.

#### **2.3.1. Directory Traversal and Entropy Analysis**

The detection logic for filesystem leftovers involves scanning specific directories known for accumulating application data: %ProgramFiles%, %ProgramData%, %APPDATA%, and %LOCALAPPDATA%.17

**The Corpse Finder Algorithm:**

1. **Keyword Extraction:** The algorithm extracts the Vendor Name and Application Name from the ARP registry keys before they are fully purged, or from a historical database of known software.  
2. **Pattern Matching:** It scans the target directories for folders matching these keywords. For example, if "Adobe Reader" is uninstalled, the scanner looks for C:\\ProgramData\\Adobe.  
3. **Cross-Referencing:** If a directory exists but no installed software maps to that vendor in the MSI database or the Uninstall registry keys, the directory is flagged as a "corpse" or orphan. This logic requires careful whitelisting to avoid false positives (e.g., deleting a folder shared by multiple apps).19

#### **2.3.2. Windows Prefetch**

The Prefetch mechanism (C:\\Windows\\Prefetch) optimizes application startup by tracing the files loaded during the first 10 seconds of execution. When a program is run, a .pf file is created (e.g., WORD.EXE-12345678.pf).

Detection Utility:  
When a program is uninstalled, the .pf files are almost never removed by the vendor uninstaller. They persist until the system limit (128 on older Windows, 1024 on newer versions) is reached or they are cycled out by newer executions. Finding a .pf file for an application that is not currently present in Program Files is a standard forensic technique for proving past execution.21

#### **2.3.3. Installer Cache (C:\\Windows\\Installer)**

This hidden system directory contains stripped versions of .msi and .msp files used for repair and uninstallation. When an installation becomes "broken" (the registry key is deleted but the installer cache remains), these files become orphaned. They contain the GUIDs of the product, allowing for reverse-lookup of the software they belong to via COM object queries or header analysis.13

## ---

**3\. The macOS Ecosystem: Bundle Identifiers and Metadata Persistence**

The macOS platform (formerly OS X) employs a different architectural paradigm centered around "Bundles" and "Containers." Unlike Windows, which relies on a central registry, macOS relies on filesystem metadata (Info.plist) and the Apple System Launch Services database. The detection of uninstalled applications on macOS hinges on tracing the unique CFBundleIdentifier.

### **3.1. The Bundle ID: The Genetic Marker of Mac Apps**

Every macOS application must have a CFBundleIdentifier defined in its Info.plist file (e.g., com.apple.safari or com.microsoft.Word). This ID acts as the primary key for the operating system to manage preferences, caches, sandboxing, and entitlements.22 Even after the .app bundle is deleted from the /Applications folder, the OS retains data associated with this ID.

Logic for Retrieving Bundle IDs of Deleted Apps:  
To detect leftovers, one must first identify the Bundle IDs of applications that were historically present.

1. **Receipts Database:** The primary source for this is /var/db/receipts/. When an application is installed via a .pkg or .dmg, the system writes a Bill of Materials (.bom) and a property list (.plist) to this directory. These files are named using the Bundle ID (e.g., com.vendor.app.bom). Even if the user drags the application to the Trash, these receipts typically persist, providing a log of the installation.24  
2. **MobileInstallation Logs:** Located in /private/var/installd/Library/Logs/MobileInstallation/, these logs provide a textual history of installation and uninstallation events, often explicitly listing the Bundle ID and the timestamp of removal.25  
3. **InstallHistory.plist:** Located at /Library/Receipts/InstallHistory.plist, this file maintains a chronological array of dictionaries describing every package installed, including its identifier, version, and date. It is a definitive log for proving past installation.24

### **3.2. The pkgutil and BOM Analysis**

For applications installed via the standard macOS installer, the pkgutil system provides a powerful mechanism for detecting residue.

The Bill of Materials (BOM) Logic:  
A .bom file is a binary database that lists every single file installed by a package, along with its permissions, size, and checksum.  
Detection Algorithm:  
A forensic script can parse the BOM files of suspected uninstalled applications using the command pkgutil \--bom path\_to\_receipt.

* **Verification Loop:** The script iterates through the file list provided by the BOM.  
* **Orphan Detection:** It checks for the existence of these files on the current filesystem. If the main application binary (e.g., /Applications/App.app) is missing, but auxiliary files listed in the BOM (such as launch daemons in /Library/LaunchDaemons/ or helpers in /usr/local/bin) are present, those auxiliary files are confirmed orphans. This method allows for surgical removal of files that generic cleaners might miss.26

### **3.3. Sandboxing and Container Heuristics**

Modern macOS applications are "sandboxed," meaning their data is stored in specific container directories to isolate them from the core system and other apps.

**The Container Evolution:**

* **Legacy (Non-Sandboxed):** Data was stored in \~/Library/Application Support/AppName and \~/Library/Preferences/com.vendor.app.plist.  
* **Modern (Sandboxed):** Data is stored in \~/Library/Containers/com.vendor.app/. In newer versions of macOS (Big Sur and later), the visible folder name might just be the App Name, but the underlying directory structure often maps a UUID or the Bundle ID to the container.28  
* **Group Containers:** Data shared between apps from the same developer (e.g., Word and Excel) is stored in \~/Library/Group Containers/.28

Detection Heuristic (AppCleaner Logic):  
Tools like AppCleaner utilize a specific heuristic to find these containers:

1. **Input:** The user selects an app or the tool scans the Receipts database for a Bundle ID.  
2. **Metadata Query:** The tool queries the Spotlight metadata store (mds) using mdfind (see section 3.4).  
3. **Path Matching:** It scans \~/Library/Containers and \~/Library/Group Containers for directories that fuzzy-match the Bundle ID or the application name.  
4. **Preference Mapping:** It checks \~/Library/Preferences for .plist files that match the reverse-DNS naming convention of the Bundle ID.

### **3.4. Spotlight and mdfind Queries**

macOS maintains a continuously updated index of file metadata to facilitate Spotlight search. This index can be queried via the command line using mdfind, offering a capability that is significantly faster than a recursive filesystem crawl.

The mdfind Logic:  
To find all traces of an application with the Bundle ID com.zerotier.ZeroTierOne after the main app is deleted:

Bash

mdfind kMDItemCFBundleIdentifier \== "com.zerotier.ZeroTierOne"

This command queries the metadata database for any file that lists that string as its bundle identifier attribute.30 This is particularly powerful because it finds files regardless of their filename or location, provided they have been indexed. It can locate cached data, preference panes, and support files that the system explicitly associates with that ID.

Limitations:  
This method relies on the Spotlight index being intact. If the index is corrupted or if the user has excluded system directories from indexing, mdfind may return incomplete results. In such cases, a fallback to standard find commands based on filename patterns is necessary.

| Feature | pkgutil / Receipts | mdfind / Spotlight | Container Scan |
| :---- | :---- | :---- | :---- |
| **Primary Key** | Package ID | Bundle ID Attribute | Directory Name |
| **Scope** | System-level installs (/Library) | Indexed User & System files | User Sandboxes (\~/Library) |
| **Detection Speed** | Moderate (Parsing binary BOMs) | Very Fast (Database query) | Slow (Directory traversal) |
| **Best For** | Removing hidden daemons/libs | Finding tagged docs/prefs | Cleaning user data/caches |

*Table 2: macOS Detection Vectors for Uninstalled Software*

## ---

**4\. Linux Distributions: Package Management and Configuration Drift**

The detection of uninstalled applications on Linux is bifurcated between the rigid, deterministic structure of package managers (APT, RPM, Pacman) and the chaotic, unmanaged nature of user-home configurations ("dotfiles").

### **4.1. The "Purge" vs. "Remove" Distinction (Debian/Ubuntu)**

On Debian-based systems (Ubuntu, Kali, Mint), the Advanced Package Tool (APT) and the underlying dpkg system make a formal distinction between removing the binaries (remove) and removing the system-wide configuration files (purge).

The "rc" Status:  
When a user runs apt-get remove package (without \--purge), the package status in the dpkg database changes to rc:

* **r**: Remove (The package is marked for removal).  
* **c**: Config-files (The configuration files are retained).32

Detection Logic:  
This provides a deterministic method for finding uninstalled applications that have left traces. The detection command queries the dpkg status database:

Bash

dpkg \-l | grep '^rc' | awk '{print $2}'

This pipeline filters the package list for lines starting with rc and extracts the package name. A cleanup script typically iterates through this list and executes dpkg \--purge on the results to remove the residual /etc/ config files.34 This logic is fundamental to maintaining system hygiene on Debian systems.

### **4.2. RPM and Unowned File Detection (Red Hat/Fedora)**

Red Hat-based systems (RHEL, Fedora, CentOS) utilize the RPM package manager. Unlike dpkg, rpm typically removes configuration files upon uninstallation unless they were modified by the user, in which case they are renamed with an extension like .rpmsave or .rpmnew.

The Unowned File Heuristic:  
A common forensic task on RPM systems is identifying files that do not belong to any currently installed package. This is useful for finding files left behind by installers that bypassed the package manager (e.g., make install) or runtime files (logs, caches) that RPM does not track.  
Algorithm:  
The logic involves a set subtraction operation: (All Files on Disk) \- (Files Claimed by RPM Database).

Bash

comm \-13 \<(rpm \-qla | sort) \<(find /usr \-type f | sort)

* rpm \-qla: Lists every file owned by every installed package.  
* find /usr \-type f: Lists every file currently in the /usr directory.  
* comm \-13: Compares the two sorted lists and outputs lines unique to the second list (files on disk that RPM does not know about).  
  These "unowned" files are high-probability candidates for orphaned data from uninstalled software.35

### **4.3. Arch Linux and the Lostfiles Script**

Arch Linux's pacman follows a similar philosophy to RPM, creating .pacsave files for modified configs. The community utilizes "lostfiles" scripts that refine the set subtraction logic used in RPM systems.

Refined Logic:  
The script logic typically excludes virtual filesystems (/proc, /sys, /dev) and user home directories (which pacman never touches) to reduce false positives. It is a brute-force method that requires root privileges to scan the entire tree, comparing valid paths against the pacman \-Ql output.37

### **4.4. The "Dotfile" Problem: User Home Directory Heuristics**

One universal challenge across all Linux distributions is that package managers rarely, if ever, touch the user's home directory (/home/user/). Applications create "dotfiles" (hidden configuration files, e.g., \~/.bashrc, \~/.config/vlc/) which persist indefinitely after the package is removed.

Heuristic Detection (BleachBit Logic):  
Tools like BleachBit employ an XML-based ruleset (CleanerML) to identify these files.

* **Deep Scan:** The tool performs deep scans searching for specific residue types (e.g., \*.tmp, Thumbs.db).38  
* **Rule-Based Matching:** It uses explicit path definitions:  
  XML  
  \<action command\="delete" search\="glob" path\="\~/.cache/mozilla/firefox/\*.default/Cache"/\>

  This approach is deterministic but requires a maintained database of application paths.  
* **Orphan Heuristic:** More advanced scripts search for directories in standard config locations (\~/.config/ or \~/.local/share/) and cross-reference the directory names against the list of installed packages. If a folder \~/.config/zoom exists, but the package zoom or zoom-client is not found in the dpkg/rpm database, the folder is flagged as a likely orphan.40 This requires fuzzy string matching, as package names often differ slightly from config folder names.

## ---

**5\. The Android Platform: The "Corpse" Finding Algorithms**

Android, while based on the Linux kernel, employs a unique user-separation model where each application runs with a distinct UID. This architecture, combined with the separation of internal and external storage, leads to specific patterns of digital residue.

### **5.1. Filesystem Hierarchy and the "Corpse" Problem**

Android storage is generally partitioned into:

1. **System Partition (/system):** Read-only, pre-installed apps.  
2. **Data Partition (/data):**  
   * /data/data/\<package\_name\>: Private internal storage. This is usually managed strictly by the OS and cleared upon uninstallation.  
3. **External/Shared Storage (/sdcard or /storage/emulated/0):**  
   * /Android/data/\<package\_name\>: The "official" public data folder.  
   * **Arbitrary Folders:** Apps frequently create custom folders on the root of the SD card (e.g., /WhatsApp, /Tencent, /Recordings).

The Detection Gap:  
When an app is uninstalled, Android's PackageManager removes the APK from /data/app and the private data from /data/data. It usually removes the structured folder in /Android/data. However, it does not track or remove the arbitrary folders created on the SD card root. These folders remain as "corpses" indefinitely.20

### **5.2. SD Maid and "CorpseFinder" Logic**

The "CorpseFinder" module in the SD Maid tool represents the industry standard for detecting these leftovers. It uses a hybrid approach of Ownership Matching and Known Path Databases.

#### **5.2.1. Ownership Matching (The Core Algorithm)**

This logic applies to structured directories where the folder name equals the package name (e.g., /Android/data/com.facebook.katana).

* **Database:** The tool queries the PackageManager API to build a list of currently installed Package Names.  
* **Scan:** It iterates through /data/app, /data/data, and /sdcard/Android/data.  
* **Comparison:** If it finds a directory named com.instagram.android but that package string is not present in the installed list, the directory is flagged as a "corpse." This is a safe, high-confidence detection method.20

#### **5.2.2. Known Path Databases (The Heuristic)**

For generic folders (e.g., /Tencent or /baidu), strict package name matching fails.

* **Logic:** The tool relies on a manually curated "Clutter Database" linking specific folder names to package names.  
  * *Rule:* Folder /Tencent is associated with com.tencent.mm (WeChat).  
  * *Check:* Is com.tencent.mm installed?  
  * *Result:* If no, flag /Tencent as a leftover. This relies on the maintainer updating the database with common app behaviors.20

### **5.3. System Artifacts: packages.xml**

For forensic investigators, the file /data/system/packages.xml is a critical artifact. It serves as the registry of installed applications, mapping Package Names to UIDs and permissions.

* **Forensic Use:** Even if an app is uninstalled, traces might linger in backup versions of this file (packages.list, packages.xml.bak) or in usage-stats logs (located in /data/system/usagestats/). These usage logs record when apps were last moved to the foreground, preserving the package name and timestamp even after the APK is physically removed from the device.41

### **5.4. Dalvik/ART Cache Residue**

Android uses the Dalvik (older) or ART (newer) runtime, which optimizes app bytecode into .dex or .oat files stored in /data/dalvik-cache.

* **Residue:** Occasionally, the system fails to delete the .dex file associated with an uninstalled app.  
* **Detection:** Tools scan this directory and check if the filename (which typically contains the package name) corresponds to an installed app. If not, it is flagged as a "safe to delete" orphan (Green risk level), because even if it is a false positive, the system will simply regenerate the cache file upon the next app launch.20

## ---

**6\. The iOS Mobile Platform: Keychain Persistence and Snapshotting**

iOS is the most "locked-down" of the platforms, employing aggressive sandboxing that prevents apps from accessing each other's data. However, a specific architectural decision regarding the **Keychain** creates a massive footprint for uninstalled apps that forensic analysts can exploit.

### **6.1. The Keychain Persistence "Feature"**

The iOS Keychain is a secure SQLite database used to store passwords, authentication tokens, and cryptographic keys. Crucially, **Keychain items are not deleted when an app is deleted.**

**The Mechanism:**

1. **Access Groups:** Apps do not access the Keychain by filename. They access it via "Keychain Access Groups" defined in their entitlements (usually in the format TeamID.com.example.app).  
2. **Persistence:** When an app is removed, the OS cleans up the App Sandbox (Documents, Library folders), but the Keychain entries associated with that Access Group remain in the secure enclave database.42  
3. **Reinstallation Effect:** If the user reinstalls the app, the app can immediately read the old Keychain data (because it possesses the same TeamID and Bundle ID). This allows apps to "remember" users or ban evaded devices even after a delete-reinstall cycle.42

**Forensic Detection:**

* **Jailbroken Devices:** Tools like keychain\_dumper can dump the decrypted contents of the SQLite database. Analysts scan for Access Groups that do not correspond to any currently installed Bundle ID.  
* **Logical Extraction:** An encrypted iTunes backup includes the Keychain. By cracking the backup password and parsing the keychain, analysts can view credentials for apps no longer present on the device, providing a timeline of past app usage.44

### **6.2. App Snapshots and Window Management**

To create the visual effect of the multitasking switcher (the "App Switcher" view), iOS takes snapshots of applications when they are sent to the background.

* **Location:** /private/var/mobile/Library/Caches/Snapshots/ (path varies slightly by iOS version).  
* **Persistence:** These snapshots (often PNG or KTX files) frequently persist after the app is uninstalled. Finding a snapshot image for a Bundle ID that is not installed is definitive visual proof of past installation and usage.47

### **6.3. Tracking Databases and Logs**

Several internal SQLite databases track app usage and do not aggressively purge data upon uninstallation:

1. **KnowledgeC.db:** This database tracks application usage (start/stop times) for Siri suggestions and Screen Time. It retains data for up to 4 weeks. Uninstalled apps appear here with their Bundle IDs, allowing analysts to reconstruct exactly when an uninstalled app was last used.48  
2. **MobileInstallation.log:** A text log that explicitly records the Uninstalling identifier event with a timestamp. This is often the "smoking gun" for determining exactly when a user removed an incriminating application.25

## ---

**7\. Advanced Cross-Platform Heuristics**

Beyond platform-specific artifacts, general computer science principles are applied in advanced forensic scenarios to detect remnants of uninstalled software.

### **7.1. Entropy and Sector Analysis**

Experimental forensic methods involve scanning the raw disk surface for data blocks with high entropy (randomness). Compressed files (like APKs, IPAs, JARs) and encrypted databases have naturally high entropy.

* **Logic:** If a sector-weighted analysis finds high-entropy blocks that do not map to the active filesystem's allocated files, they may be remnants of deleted application packages or encrypted databases that have not yet been overwritten. This is a "file carving" technique adapted for package detection.50

### **7.2. Timeline Analysis (Temporal Proximity)**

Forensic tools use "temporal proximity" to associate orphan files with known uninstallation events.

* **Scenario:** A user uninstalls "Malware.exe" at 10:00:00 AM.  
* **Heuristic:** The tool scans the ShimCache or MFT (Master File Table) for other files created, modified, or deleted within \+/- 2 seconds of that timestamp. This helps identify dropped temporary files, logs, or config files that do not share the malware's name but were part of its execution or uninstallation chain.13

### **7.3. Differential Analysis (Snapshotting)**

Tools like Revo Uninstaller Pro use a "monitoring" approach rather than just post-hoc scanning.

* **Logic:**  
  1. **Pre-Install Snapshot:** Record the state of the Registry and File System.  
  2. **Installation:** Allow the installer to run.  
  3. **Post-Install Snapshot:** Record the new state.  
  4. **Log Creation:** Create a detailed log of every key and file created.  
  5. **Uninstallation:** Use this log to reverse every specific action. This guarantees 100% removal, unlike heuristic scanning which guesses based on patterns.3

## ---

**8\. Conclusion**

The detection of uninstalled applications is a discipline that operates in the gap between the intended behavior of an operating system and its actual implementation. While all major platforms provide mechanisms for uninstallation (MSIExec on Windows, dpkg on Linux, pkgutil on macOS), none enforce a strict "zero-knowledge" state after removal.

* **Windows** relies heavily on the Registry, where the SharedDLLs counter, AmCache SHA-1 hashes, and ShimCache execution history provide the most durable evidence of past existence.  
* **macOS** utilizes the Bundle ID as a persistent thread connecting receipts, containers, and Spotlight metadata, allowing for rapid detection via mdfind.  
* **Linux** detection relies on distinguishing between "removed" and "purged" packages in the database, and managing the inevitable configuration drift in user directories via heuristic scanning.  
* **Android** suffers from the decoupling of the SD card file structure from the Package Manager, necessitating "Corpse Finder" logic that matches folder names to known packages.  
* **iOS** presents a unique privacy paradox where the Keychain retains authentication tokens indefinitely, turning the secure storage mechanism into a persistent tracking vector for uninstalled apps.

For the forensic analyst, the absence of an application binary is merely the beginning of the investigation. The "ghosts" of the software remain in the databases, caches, and configuration files designed to optimize the user experience, providing an indelible record of digital history.

#### **Works cited**

1. Safely Clean Your Windows Registry: Step-By-Step Guide | Trend Micro Help Center, accessed January 7, 2026, [https://helpcenter.trendmicro.com/en-us/article/tmka-20814](https://helpcenter.trendmicro.com/en-us/article/tmka-20814)  
2. Removing Invalid Entries in the Add/Remove Programs Tool \- Microsoft Support, accessed January 7, 2026, [https://support.microsoft.com/en-us/topic/removing-invalid-entries-in-the-add-remove-programs-tool-0dae27c1-0b06-2559-311b-635cd532a6d5](https://support.microsoft.com/en-us/topic/removing-invalid-entries-in-the-add-remove-programs-tool-0dae27c1-0b06-2559-311b-635cd532a6d5)  
3. Remove unwanted programs easily with Revo Uninstaller Pro, accessed January 7, 2026, [https://www.revouninstaller.com/products/revo-uninstaller-pro/](https://www.revouninstaller.com/products/revo-uninstaller-pro/)  
4. Revo Uninstaller Pro, accessed January 7, 2026, [https://www.revouninstaller.com/online-manual/uninstaller/](https://www.revouninstaller.com/online-manual/uninstaller/)  
5. windows 7 \- Removing bad installs from Add/Remove programs \- Stack Overflow, accessed January 7, 2026, [https://stackoverflow.com/questions/18109387/removing-bad-installs-from-add-remove-programs](https://stackoverflow.com/questions/18109387/removing-bad-installs-from-add-remove-programs)  
6. Shared DLLs, accessed January 7, 2026, [https://www2.isye.gatech.edu/\~mgoetsch/cali/Windows%20Configuration/Windows%20Configuration%20Html/SharedDLLs.htm](https://www2.isye.gatech.edu/~mgoetsch/cali/Windows%20Configuration/Windows%20Configuration%20Html/SharedDLLs.htm)  
7. Shared DLLs Registry References \- Application Packaging \- WordPress.com, accessed January 7, 2026, [https://winscripting.wordpress.com/2018/10/01/shared-dlls-registry-references/](https://winscripting.wordpress.com/2018/10/01/shared-dlls-registry-references/)  
8. Cleaning Up Your Shared DLLs Registry References for MSIs | Revenera Blog, accessed January 7, 2026, [https://www.revenera.com/blog/software-installation/cleaning-up-your-shared-dlls-registry-references-for-msis/](https://www.revenera.com/blog/software-installation/cleaning-up-your-shared-dlls-registry-references-for-msis/)  
9. Best practice for removing an installed, registered DLL \[Archive\] \- SetupBuilder Community, accessed January 7, 2026, [https://www.lindersoft.com/forums/archive/index.php/t-44716.html](https://www.lindersoft.com/forums/archive/index.php/t-44716.html)  
10. Windows Registry Forensics: Analysis Techniques \- Belkasoft, accessed January 7, 2026, [https://belkasoft.com/windows-registry-analysis-techniques](https://belkasoft.com/windows-registry-analysis-techniques)  
11. Residuals and left over registries and services of uninstalled programs \- Microsoft Learn, accessed January 7, 2026, [https://learn.microsoft.com/en-us/answers/questions/3822684/residuals-and-left-over-registries-and-services-of](https://learn.microsoft.com/en-us/answers/questions/3822684/residuals-and-left-over-registries-and-services-of)  
12. ShimCache vs AmCache: Key Windows Forensic Artifacts, accessed January 7, 2026, [https://www.magnetforensics.com/blog/shimcache-vs-amcache-key-windows-forensic-artifacts/](https://www.magnetforensics.com/blog/shimcache-vs-amcache-key-windows-forensic-artifacts/)  
13. ShimCache and AmCache Forensic Analysis 2025 \- Cyber Triage, accessed January 7, 2026, [https://www.cybertriage.com/blog/shimcache-and-amcache-forensic-analysis-2025/](https://www.cybertriage.com/blog/shimcache-and-amcache-forensic-analysis-2025/)  
14. Windows Forensics : ShimCache and AmCache | by @omayma | Medium, accessed January 7, 2026, [https://medium.com/@omaymaW/windows-forensics-shimcache-and-amcache-ead4812f9a73](https://medium.com/@omaymaW/windows-forensics-shimcache-and-amcache-ead4812f9a73)  
15. AmCache artifact: forensic value and a tool for data extraction | Securelist, accessed January 7, 2026, [https://securelist.com/amcache-forensic-artifact/117622/](https://securelist.com/amcache-forensic-artifact/117622/)  
16. Amcache vs Shimcache in Digital Forensics \- SalvationDATA, accessed January 7, 2026, [https://www.salvationdata.com/knowledge/amcache-vs-shimcache/](https://www.salvationdata.com/knowledge/amcache-vs-shimcache/)  
17. Uninstalling Software | Anti-Forensics \- Insider Threat Matrix, accessed January 7, 2026, [https://insiderthreatmatrix.org/articles/AR5/sections/AF016](https://insiderthreatmatrix.org/articles/AR5/sections/AF016)  
18. Klocman Bulk-Crap-Uninstaller · Discussions \- GitHub, accessed January 7, 2026, [https://github.com/Klocman/Bulk-Crap-Uninstaller/discussions](https://github.com/Klocman/Bulk-Crap-Uninstaller/discussions)  
19. How does the app SD Maid find leftover files from apps that the user has already uninstalled? : r/AndroidQuestions \- Reddit, accessed January 7, 2026, [https://www.reddit.com/r/AndroidQuestions/comments/166j4v1/how\_does\_the\_app\_sd\_maid\_find\_leftover\_files\_from/](https://www.reddit.com/r/AndroidQuestions/comments/166j4v1/how_does_the_app_sd_maid_find_leftover_files_from/)  
20. CorpseFinder · d4rken-org/sdmaid Wiki · GitHub, accessed January 7, 2026, [https://github.com/d4rken-org/sdmaid/wiki/Corpsefinder](https://github.com/d4rken-org/sdmaid/wiki/Corpsefinder)  
21. Here is a List of Windows Forensic Artifacts possible (upper) locations, what is missing ? : r/computerforensics \- Reddit, accessed January 7, 2026, [https://www.reddit.com/r/computerforensics/comments/7pn7dl/here\_is\_a\_list\_of\_windows\_forensic\_artifacts/](https://www.reddit.com/r/computerforensics/comments/7pn7dl/here_is_a_list_of_windows_forensic_artifacts/)  
22. How to find the bundle ID for an application \- SimpleMDM, accessed January 7, 2026, [https://simplemdm.com/blog/how-to-find-the-bundle-id-for-an-application/](https://simplemdm.com/blog/how-to-find-the-bundle-id-for-an-application/)  
23. Bundle Structures \- Apple Developer, accessed January 7, 2026, [https://developer.apple.com/go/?id=bundle-structure](https://developer.apple.com/go/?id=bundle-structure)  
24. The macOS Forensic Journey — Software Installation History | by Shlomi Boutnaru, Ph.D., accessed January 7, 2026, [https://medium.com/@boutnaru/the-macos-forensic-journey-software-installation-history-63f3dc3b8115](https://medium.com/@boutnaru/the-macos-forensic-journey-software-installation-history-63f3dc3b8115)  
25. How to identify uninstalled apps under iOS? : r/computerforensics \- Reddit, accessed January 7, 2026, [https://www.reddit.com/r/computerforensics/comments/z11m8i/how\_to\_identify\_uninstalled\_apps\_under\_ios/](https://www.reddit.com/r/computerforensics/comments/z11m8i/how_to_identify_uninstalled_apps_under_ios/)  
26. macOS Malware Analysis : PKG Files \- Malwr4n6, accessed January 7, 2026, [https://www.malwr4n6.com/post/macos-malware-analysis-pkg-files](https://www.malwr4n6.com/post/macos-malware-analysis-pkg-files)  
27. How to reverse engineer a malicious macOS pkg installer?, accessed January 7, 2026, [https://tonygo.tech/blog/2025/how-to-reverse-engineer-malicious-macos-pkg-installer](https://tonygo.tech/blog/2025/how-to-reverse-engineer-malicious-macos-pkg-installer)  
28. cant find containers folder? has this changed with Ventura? \- Apple Discussions, accessed January 7, 2026, [https://discussions.apple.com/thread/254549241](https://discussions.apple.com/thread/254549241)  
29. What are all those Containers? \- The Eclectic Light Company, accessed January 7, 2026, [https://eclecticlight.co/2024/08/05/what-are-all-those-containers/](https://eclecticlight.co/2024/08/05/what-are-all-those-containers/)  
30. Using the mdfind command line tool to find duplicate copies of an application on macOS Sequoia | Der Flounder, accessed January 7, 2026, [https://derflounder.wordpress.com/2025/07/28/using-the-mdfind-command-line-tool-to-find-duplicate-copies-of-an-application-on-macos-sequoia/](https://derflounder.wordpress.com/2025/07/28/using-the-mdfind-command-line-tool-to-find-duplicate-copies-of-an-application-on-macos-sequoia/)  
31. Locating an app by its bundle identifier from the command line \- Apple StackExchange, accessed January 7, 2026, [https://apple.stackexchange.com/questions/115947/locating-an-app-by-its-bundle-identifier-from-the-command-line](https://apple.stackexchange.com/questions/115947/locating-an-app-by-its-bundle-identifier-from-the-command-line)  
32. Can I purge configuration files after I've removed the package? \- Ask Ubuntu, accessed January 7, 2026, [https://askubuntu.com/questions/104126/can-i-purge-configuration-files-after-ive-removed-the-package](https://askubuntu.com/questions/104126/can-i-purge-configuration-files-after-ive-removed-the-package)  
33. What exactly does "apt purge ?config-files" do? \- Unix & Linux Stack Exchange, accessed January 7, 2026, [https://unix.stackexchange.com/questions/758736/what-exactly-does-apt-purge-config-files-do](https://unix.stackexchange.com/questions/758736/what-exactly-does-apt-purge-config-files-do)  
34. Is Not Installed (Residual config) safe to remove all? \- Ask Ubuntu, accessed January 7, 2026, [https://askubuntu.com/questions/376253/is-not-installed-residual-config-safe-to-remove-all](https://askubuntu.com/questions/376253/is-not-installed-residual-config-safe-to-remove-all)  
35. How do I list all the files not owned by any package in a RPM-based system? \- Super User, accessed January 7, 2026, [https://superuser.com/questions/555918/how-do-i-list-all-the-files-not-owned-by-any-package-in-a-rpm-based-system](https://superuser.com/questions/555918/how-do-i-list-all-the-files-not-owned-by-any-package-in-a-rpm-based-system)  
36. \[BASH\] 'one-liner' find files not owned by RPMs (could easily be adapted for Debian, etc) : r/commandline \- Reddit, accessed January 7, 2026, [https://www.reddit.com/r/commandline/comments/25nn6m/bash\_oneliner\_find\_files\_not\_owned\_by\_rpms\_could/](https://www.reddit.com/r/commandline/comments/25nn6m/bash_oneliner_find_files_not_owned_by_rpms_could/)  
37. pacman/Tips and tricks \- ArchWiki, accessed January 7, 2026, [https://wiki.archlinux.org/title/Pacman/Tips\_and\_tricks](https://wiki.archlinux.org/title/Pacman/Tips_and_tricks)  
38. General Usage \- BleachBit Documentation, accessed January 7, 2026, [https://docs.bleachbit.org/doc/general-usage.html](https://docs.bleachbit.org/doc/general-usage.html)  
39. Introduction \- BleachBit Documentation, accessed January 7, 2026, [https://docs.bleachbit.org/cml/cleanerml.html](https://docs.bleachbit.org/cml/cleanerml.html)  
40. How to identify and remove orphaned config files of uninstalled Software?, accessed January 7, 2026, [https://unix.stackexchange.com/questions/411382/how-to-identify-and-remove-orphaned-config-files-of-uninstalled-software](https://unix.stackexchange.com/questions/411382/how-to-identify-and-remove-orphaned-config-files-of-uninstalled-software)  
41. Android System Artifacts: Forensic Analysis of Application Usage \- Belkasoft, accessed January 7, 2026, [https://belkasoft.com/android-system-artifacts-forensic-analysis-of-application-usage](https://belkasoft.com/android-system-artifacts-forensic-analysis-of-application-usage)  
42. IOS Saves Credentials for Deleted Apps \- Apple Communities, accessed January 7, 2026, [https://discussions.apple.com/thread/255712703](https://discussions.apple.com/thread/255712703)  
43. \[docs\] \[expo-secure-store\] Documentation inconsistency: iOS Keychain data persists after app uninstallation · Issue \#40662 \- GitHub, accessed January 7, 2026, [https://github.com/expo/expo/issues/40662](https://github.com/expo/expo/issues/40662)  
44. iOS Keychain and Data Protection Classes Abuse and Misuse | by Farhad Sajid Barbhuiya, accessed January 7, 2026, [https://medium.com/@salamsajid7/ios-keychain-and-data-protection-classes-abuse-and-misuse-759267ee03b4](https://medium.com/@salamsajid7/ios-keychain-and-data-protection-classes-abuse-and-misuse-759267ee03b4)  
45. iOS: credentials persist after app uninstall \- Esri Community, accessed January 7, 2026, [https://community.esri.com/t5/flutter-maps-sdk-questions/ios-credentials-persist-after-app-uninstall/td-p/1611867](https://community.esri.com/t5/flutter-maps-sdk-questions/ios-credentials-persist-after-app-uninstall/td-p/1611867)  
46. Forensic Analysis on iOS Devices \- GIAC Certifications, accessed January 7, 2026, [https://www.giac.org/paper/gcfe/809/forensic-analysis-ios-devices/108622](https://www.giac.org/paper/gcfe/809/forensic-analysis-ios-devices/108622)  
47. Exploring Data Extraction from iOS Devices: What Data You Can Access and How, accessed January 7, 2026, [https://blog.digital-forensics.it/2025/09/exploring-data-extraction-from-ios.html](https://blog.digital-forensics.it/2025/09/exploring-data-extraction-from-ios.html)  
48. iOS \- AboutDFIR \- The Definitive Compendium Project, accessed January 7, 2026, [https://aboutdfir.com/toolsandartifacts/ios/](https://aboutdfir.com/toolsandartifacts/ios/)  
49. iOS \- Tracking Traces of Deleted Applications \- D20 Forensics, accessed January 7, 2026, [https://blog.d204n6.com/2019/09/ios-tracking-traces-of-deleted.html](https://blog.d204n6.com/2019/09/ios-tracking-traces-of-deleted.html)  
50. Inferring Previously Uninstalled Applications from Residual Partial Artifacts \- Scholarly Commons, accessed January 7, 2026, [https://commons.erau.edu/context/adfsl/article/1356/viewcontent/Inferring\_Previously\_Uninstalled\_Applications\_from\_Residual\_Partial\_Artifacts.pdf](https://commons.erau.edu/context/adfsl/article/1356/viewcontent/Inferring_Previously_Uninstalled_Applications_from_Residual_Partial_Artifacts.pdf)