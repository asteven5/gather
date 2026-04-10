-- Gather — Home Video Maker
-- AppleScript applet wrapper: launches the Python/FastAPI backend via uv,
-- keeps the dock icon alive, and quits when the server exits.
--
-- Supports three layouts (checked in order):
--   1. Bundled:  <app>/Contents/Resources/app/main.py  (distribution)
--   2. Internal: <app>/../_internal/main.py             (alt distribution)
--   3. Flat:     <app>/../main.py                       (dev)

use AppleScript version "2.4"
use framework "AppKit"
use scripting additions

property launchTime : missing value

on run
	set launchTime to current date

	set appPath to POSIX path of (path to me)
	set parentDir to do shell script "cd " & quoted form of appPath & "/.. && pwd"
	set bundledDir to appPath & "Contents/Resources/app"

	-- Pick the first layout that has main.py
	set workDir to ""
	repeat with candidate in {bundledDir, parentDir & "/_internal", parentDir}
		try
			do shell script "test -f " & quoted form of (candidate & "/main.py")
			set workDir to candidate as text
			exit repeat
		end try
	end repeat

	if workDir is "" then
		display dialog "Could not find main.py — is the app damaged?" buttons {"OK"} default button "OK" with icon stop
		quit
		return
	end if

	set mainPy to workDir & "/main.py"
	set reqFile to workDir & "/requirements.txt"
	set logFile to "/tmp/gather.log"
	set envSetup to "export PATH=$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

	-- Warmup: establish PATH and let uv initialize its cache
	do shell script envSetup & " && echo \"launch $(date)\" > " & quoted form of logFile
	do shell script envSetup & " && uv --version >> " & quoted form of logFile & " 2>&1"

	-- Launch in background — applet stays open via OSAAppletStayOpen
	do shell script envSetup & " && cd " & quoted form of workDir & " && uv run --with-requirements " & quoted form of reqFile & " " & quoted form of mainPy & " >> " & quoted form of logFile & " 2>&1 &"
end run

on reopen
	-- Bring the pywebview window to front when dock icon is clicked.
	try
		do shell script "curl -s http://127.0.0.1:8000/focus > /dev/null 2>&1"
	end try
end reopen

on idle
	-- Grace period: give Python time to start up
	if (current date) - launchTime < 20 then
		return 3
	end if

	-- Quit the applet when the server is no longer running
	try
		do shell script "lsof -ti :8000"
	on error
		quit
	end try
	return 3
end idle
