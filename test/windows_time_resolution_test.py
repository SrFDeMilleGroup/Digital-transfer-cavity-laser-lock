import ctypes

min_res = ctypes.c_ulong()
max_res = ctypes.c_ulong()
cur_res = ctypes.c_ulong()

ctypes.windll.ntdll.NtQueryTimerResolution(ctypes.byref(max_res), ctypes.byref(min_res), ctypes.byref(cur_res))

print(min_res.value)
print(max_res.value)
print(cur_res.value)

# current_res = ctypes.c_ulong()

# units are in 100 ns
# ctypes.windll.ntdll.NtSetTimerResolution(15000, True, ctypes.byref(current_res))
# print(current_res.value)

# ctypes.windll.ntdll.NtQueryTimerResolution(ctypes.byref(max_res), ctypes.byref(min_res), ctypes.byref(cur_res))
#
# print(min_res.value)
# print(max_res.value)
# print(cur_res.value)
