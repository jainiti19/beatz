#!/bin/bash
# Source this file to set up Android development environment:
#   source env-setup.sh

export ANDROID_HOME=~/Android
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

echo "Android SDK configured:"
echo "  ANDROID_HOME=$ANDROID_HOME"
echo "  Android Studio: ~/Android/android-studio/bin/studio.sh"
echo "  Emulator AVD: Pixel7_API34"
echo ""
echo "Useful commands:"
echo "  studio.sh          - Launch Android Studio"
echo "  emulator -avd Pixel7_API34  - Launch emulator"
echo "  ./gradlew assembleDebug     - Build debug APK"
