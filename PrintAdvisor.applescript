property scriptDir : "/Users/anthonysalinas/claude-workspace/print-advisor"
property pythonBin : "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
property baseProject : scriptDir & "/base.3mf"

on run
	display dialog "Drag an STL file onto this app to generate a print-settings report and/or a ready-to-slice ElegooSlicer project file." buttons {"OK"} default button "OK"
end run

on open theFiles
	-- Guard against a known AppleScript quirk: dropping exactly one file can
	-- hand "open" a bare alias/string instead of a list containing one item,
	-- which then makes "repeat...in" iterate character-by-character.
	if class of theFiles is not list then set theFiles to {theFiles}

	repeat with i from 1 to count of theFiles
		set anItem to item i of theFiles
		try
			set stlPath to POSIX path of (anItem as alias)
		on error
			set stlPath to anItem as text
		end try
		if stlPath ends with ".stl" or stlPath ends with ".STL" then
			my processFile(stlPath)
		else
			display dialog "Skipping (not an .stl file):" & return & stlPath buttons {"OK"} default button "OK"
		end if
	end repeat
end open

on processFile(stlPath)
	set projectChoice to choose from list {"functional", "decor", "structural", "figure", "test"} with prompt "What is this part for?" default items {"structural"} without multiple selections allowed
	if projectChoice is false then return
	set projectType to item 1 of projectChoice

	set materialChoice to choose from list {"pla", "pla_plus", "petg", "petg_cf", "tpu", "paht_cf", "ppa_cf", "pa12_cf", "pa6_cf", "pps_cf"} with prompt "What material?" default items {"pla"} without multiple selections allowed
	if materialChoice is false then return
	set materialType to item 1 of materialChoice

	set actionChoice to choose from list {"Ready-to-slice .3mf file", "Text report only", "Both"} with prompt "What do you want?" default items {"Ready-to-slice .3mf file"} without multiple selections allowed
	if actionChoice is false then return
	set actionType to item 1 of actionChoice

	set baseNameNoExt to my stripExtension(stlPath)

	if actionType is "Text report only" or actionType is "Both" then
		set reportPath to baseNameNoExt & "-report.txt"
		try
			set cmd to quoted form of pythonBin & " " & quoted form of (scriptDir & "/print_advisor.py") & " " & quoted form of stlPath & " --project " & projectType & " --material " & materialType & " > " & quoted form of reportPath
			do shell script cmd
			display notification "Report saved next to the STL" with title "Print Advisor"
			do shell script "open " & quoted form of reportPath
		on error errMsg
			display dialog "Report generation failed:" & return & errMsg buttons {"OK"} default button "OK"
			return
		end try
	end if

	if actionType is "Ready-to-slice .3mf file" or actionType is "Both" then
		set outPath to baseNameNoExt & "-advised.3mf"
		try
			set cmd to quoted form of pythonBin & " " & quoted form of (scriptDir & "/patch_elegoo_project.py") & " " & quoted form of baseProject & " " & quoted form of stlPath & " --project " & projectType & " --material " & materialType & " --out " & quoted form of outPath
			do shell script cmd
			tell application "Finder"
				reveal (POSIX file outPath)
				activate
			end tell
			display notification "Ready-to-slice file created" with title "Print Advisor"
		on error errMsg
			display dialog "3MF generation failed:" & return & errMsg buttons {"OK"} default button "OK"
			return
		end try
	end if
end processFile

on stripExtension(p)
	if p ends with ".stl" then
		return text 1 thru -5 of p
	else if p ends with ".STL" then
		return text 1 thru -5 of p
	else
		return p
	end if
end stripExtension