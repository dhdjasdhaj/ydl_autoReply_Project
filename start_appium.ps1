$ErrorActionPreference = "Stop"

$env:ANDROID_HOME = "C:\Users\Redmi\Android\Sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:JAVA_HOME = "C:\Users\Redmi\.jdks\openjdk-23.0.2"
$env:Path = "$env:ANDROID_HOME\platform-tools;$env:JAVA_HOME\bin;$env:Path"

Write-Host "ANDROID_HOME=$env:ANDROID_HOME"
Write-Host "JAVA_HOME=$env:JAVA_HOME"
Write-Host "Starting Appium on http://127.0.0.1:4723"
appium
