$ErrorActionPreference = "Stop"

$env:ANDROID_HOME = "C:\Users\stc_0\Android\Sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:JAVA_HOME = "C:\Users\stc_0\.jdks\ms-17.0.15"
$env:Path = "$env:ANDROID_HOME\platform-tools;$env:JAVA_HOME\bin;$env:Path"

streamlit run streamlit_app.py --server.headless true --server.port 8501
