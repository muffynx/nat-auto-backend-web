import re

def format_configuration(log_content):
    formatted_config = []

    # 1. Extract raw config section (เฉพาะส่วน display current-configuration)
    match = re.search(r"display current-configuration\s*\n(.*?)return", log_content, re.DOTALL)
    if not match:
        return "Error: Could not find configuration in log."
    
    raw_config = match.group(1)
    
    # 2. Process Hostname
    hostname_match = re.search(r"sysname\s+(\S+)", raw_config)
    if hostname_match:
        formatted_config.append(f"hostname {hostname_match.group(1)}\n")

    # 3. Process Banner (ตัวอย่าง)
    # หา header legal หรือ banner motd แล้วจัด format ใหม่
    # ... (code to extract banner) ...
    formatted_config.append("banner motd #\n" + "*"*80 + "\n" + "WARNING! ... (ใส่เนื้อหา banner) ..." + "\n" + "*"*80 + "\n#\n")

    # 4. Process VLANs
    # Comware: vlan 61 \n description HELP-01
    # Aruba: vlan 61 \n name "HELP-01" (หรือ description)
    vlan_sections = re.findall(r"vlan (\d+)\s+(?:description (.*?)\s+)?#", raw_config, re.DOTALL)
    for vlan_id, desc in vlan_sections:
        formatted_config.append(f"vlan {vlan_id}")
        if desc:
            formatted_config.append(f"   name \"{desc.strip()}\"") # Aruba มักใช้ name
        formatted_config.append("#") # ปิดท้าย vlan block

    # 5. Process Interfaces (ตัวอย่างแปลง GE1/0/1 -> 1/1/1)
    # ต้องเขียน logic การแปลงชื่อ interface ให้ตรงกับ hardware เป้าหมาย
    interfaces = re.findall(r"interface ([^\n]+)\n(.*?)(?=#)", raw_config, re.DOTALL)
    for int_name, int_config in interfaces:
        # แปลงชื่อ Interface (สมมติว่าเป็น Stack หรือ Module เดียวกัน)
        new_int_name = int_name.replace("GigabitEthernet", "").replace("Ten-GigabitEthernet", "")
        # อาจต้องปรับ format เลข port เช่น 1/0/1 -> 1/1/1 (ขึ้นอยู่กับรุ่น switch)
        
        formatted_config.append(f"interface {new_int_name}")
        
        # แปลง config ภายใน interface
        if "port access vlan" in int_config:
            vlan = re.search(r"port access vlan (\d+)", int_config).group(1)
            formatted_config.append(f"   vlan access {vlan}") # Aruba style
        
        if "shutdown" not in int_config:
             formatted_config.append("   no shutdown")
        
        # ... (แปลงคำสั่งอื่นๆ เช่น trunk, description) ...
        
        formatted_config.append("#")

    # 6. Process Routes
    routes = re.findall(r"ip route-static (\S+) (\S+) (\S+)", raw_config)
    for dest, mask, next_hop in routes:
        # แปลง mask 0.0.0.0 เป็น /0 หรือ 0.0.0.0 ตามต้องการ
        formatted_config.append(f"ip route {dest} {mask} {next_hop}")

    # ... จัดการส่วนอื่นๆ NTP, Timezone, SNMP ...

    return "\n".join(formatted_config)

# --- วิธีใช้งาน ---
with open("172.17.61.250 B3F1-14-20-04.log", "r") as f:
    log_data = f.read()
    new_config = format_configuration(log_data)
    print(new_config)