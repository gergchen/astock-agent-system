Set UAC = CreateObject("Shell.Application")
UAC.ShellExecute "python", "E:\claude\魔兽\extract_cookies.py", "", "runas", 1
