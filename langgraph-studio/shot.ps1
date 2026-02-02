Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

# Open browser and wait
Start-Process 'http://localhost:5173/bubble-test.html'
Start-Sleep -Seconds 3

# Activate browser window
$wshell = New-Object -ComObject wscript.shell
$wshell.AppActivate('Bubble Test')
Start-Sleep -Seconds 1

# Take screenshot
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save('C:\01_work\00_Git\toybox\AiAgentGame2\langgraph-studio\bubble-result.png')
$graphics.Dispose()
$bitmap.Dispose()
