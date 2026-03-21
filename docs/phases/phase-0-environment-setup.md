# Phase 0: Environment Setup

**Status:** NOT STARTED
**Estimated Effort:** 4-6 hours
**Goal:** Working dev environment with "Hello Beatz" running on emulator.

---

## Step-by-Step Guide

### 1. Install Android Studio
1. Go to https://developer.android.com/studio
2. Download the Linux `.tar.gz` (or use snap: `sudo snap install android-studio --classic`)
3. Extract and run `studio.sh`
4. On first launch, accept all defaults and let it download SDK components (takes 15-30 min)

### 2. Configure SDK
1. Open **Tools > SDK Manager**
2. Install:
   - Android 14 (API 34) SDK Platform
   - Android SDK Build-Tools 34+
   - Android Emulator
   - Intel x86 or ARM system images for API 34

### 3. Set Up Emulator
1. **Tools > Device Manager > Create Device**
2. Pick **Pixel 7**, click Next
3. Select **API 34** system image, download if needed
4. Finish — boot it to verify it works
5. Enable KVM on Linux for hardware acceleration:
   ```bash
   sudo apt install qemu-kvm
   sudo adduser $USER kvm
   ```

### 4. Create the Project
1. **File > New > New Project**
2. Template: **Empty Compose Activity**
3. Settings:
   - Name: `Beatz`
   - Package: `com.beatz.app`
   - Language: Kotlin
   - Minimum SDK: API 26 (Android 8.0)
   - Build config: Kotlin DSL (.kts)
4. Wait for Gradle sync (first time is slow)

### 5. Run It
1. Select the Pixel 7 emulator from the device dropdown
2. Click the green **Run** button
3. You should see the default Compose text
4. Change it to "Hello Beatz" and hot-reload

### 6. Connect to Git
1. Copy the Android project files into `/home/iti/git-repos/beatz/`
2. The `docs/` folder already exists there — the app files go alongside it
3. Add `.gitignore` (see template below)
4. `git add . && git commit -m "Phase 0: Initial project setup"`

### .gitignore Template
```
*.iml
.gradle/
/local.properties
/.idea/
/build/
/app/build/
/captures
.externalNativeBuild/
.cxx/
*.apk
*.aab
*.ap_
*.dex
```

### 7. Create Package Structure
Create these empty packages under `app/src/main/java/com/beatz/app/`:
```
ui/screens/
ui/components/
ui/theme/
ui/navigation/
viewmodel/
audio/decoder/
audio/analysis/
audio/engine/
audio/export/
data/model/
data/repository/
di/
util/
```

---

## Verification Checklist
- [ ] Android Studio opens without errors
- [ ] Emulator boots and shows the home screen
- [ ] App runs and displays "Hello Beatz"
- [ ] Project is committed to git
- [ ] Package folders exist
