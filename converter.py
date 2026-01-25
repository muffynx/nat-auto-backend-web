import re
import pandas as pd
import io



class ConfigConverter:
    def __init__(self, source_type, target_type, input_data):
        self.source = source_type
        self.target = target_type
        
        # input_data รับได้ทั้ง string (Log) และ bytes (Excel)
        self.input_data = input_data
        
        # ถ้าส่งมาเป็น Text ให้ map เข้า raw_log ด้วย (เพื่อให้ Parser เดิมทำงานได้)
        self.raw_log = input_data if isinstance(input_data, str) else None

        self.data = {
            "hostname": "Switch",
            "banner": "",
            "vlans": {},        # vid -> { name, ip, mask, ipv6 }
            "routes": [],       # static routes
            "interfaces": {}    # port -> role data
        }

    # ================= MAIN =================
    def process(self):
        if self.source == "excel":
            try:
                self._parse_excel()
            except Exception as e:
                return f"Error parsing Excel: {str(e)}"
# 2. Parse Text Log (Logic เดิม)
        elif isinstance(self.input_data, str): 
            self.raw_log = self.input_data
            if not self.raw_log: return "Error: Empty log"
            
            # Clean Headers
            for header in ["display current-configuration", "show running-config"]:
                if header in self.raw_log:
                    self.raw_log = self.raw_log.split(header, 1)[1]

            if self.source == "hp_comware":
                self._parse_comware()
            elif self.source == "cisco_ios":
                self._parse_cisco_ios()
            else:
                return f"Error: Source {self.source} not supported"
        else:
            return "Error: Invalid input format"

# 3. Generate Config
        if self.target in ("aruba_cx", "aruba_os_switch"):
            return self._generate_aruba_cx_ready_to_paste()
        elif self.target == "cisco_ios":
            return "Error: Cisco Generator coming soon..." # เผื่ออนาคต
        elif self.target == "hp_comware":
            return "Error: Comware Generator coming soon..." # เผื่ออนาคต

        return f"Error: Target {self.target} not supported"


# ================= EXPORTER (Log -> Excel) 🆕 =================
    def export_to_excel(self):
        # สร้าง Buffer ใน Memory (ไม่ต้องเขียนไฟล์ลง Disk)
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter')

        # 1. Sheet: Global
        df_global = pd.DataFrame([
            {'Parameter': 'Hostname', 'Value': self.data.get('hostname', '')},
            {'Parameter': 'Banner', 'Value': 'Configured' if self.data.get('banner') else 'None'},
            {'Parameter': 'VLAN_Count', 'Value': len(self.data.get('vlans', {}))},
            {'Parameter': 'Interface_Count', 'Value': len(self.data.get('interfaces', {}))},
            {'Parameter': 'Route_Count', 'Value': len(self.data.get('routes', []))}
        ])

        df_global.to_excel(writer, sheet_name='Global', index=False)

        # 2. Sheet: VLANs
        vlan_list = []
        for vid, v in self.data['vlans'].items():
            vlan_list.append({
                'ID': vid,
                'Name': v['name'],
                'IPv4': v['ip'],
                'Mask': v['mask'],
                'IPv6': v['ipv6']
            })
        pd.DataFrame(vlan_list).to_excel(writer, sheet_name='VLANs', index=False)

        # 3. Sheet: Interfaces
        iface_list = []
        # เรียงพอร์ตให้สวยงาม
        sorted_ports = sorted(self.data['interfaces'].keys(), key=self._iface_sort_key)
        
        for port in sorted_ports:
            i = self.data['interfaces'][port]
            
            # แปลง Set เป็น String "10,20,30"
            allowed_str = ""
            if i['allowed_vlans']:
                allowed_str = ",".join(map(str, sorted(list(i['allowed_vlans']))))

            iface_list.append({
                'Port': port,
                'Description': i['description'],
                'Role': i['role'] if i['role'] else '',
                'Access_VLAN': i['access_vlan'] if i['role'] == 'access' else '',
                'Native_VLAN': i['native_vlan'] if i['role'] == 'trunk' else '',
                'Allowed_VLANs': allowed_str,
                'LAG_ID': i['lag_id'] if i['lag_id'] else '',
                'Shutdown': 'Yes' if i['shutdown'] else 'No'
            })
        pd.DataFrame(iface_list).to_excel(writer, sheet_name='Interfaces', index=False)

        # 4. Sheet: Routes
        route_list = []
        for r in self.data['routes']:
            route_list.append({
                'Destination': r['dest'],
                'Mask': r['mask'],
                'Next_Hop': r['next_hop']
            })
        pd.DataFrame(route_list).to_excel(writer, sheet_name='Routes', index=False)
        workbook  = writer.book
        worksheet = writer.sheets['Interfaces']

        # ------------------------
        # Formats
        # ------------------------
        header_fmt = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'middle',
            'border': 1,
            'bg_color': '#D9E1F2'
        })

        access_fmt = workbook.add_format({
            'bg_color': '#E2EFDA',  # เขียวอ่อน
            'border': 1
        })

        trunk_fmt = workbook.add_format({
            'bg_color': '#FFF2CC',  # เหลืองอ่อน
            'border': 1
        })

        default_fmt = workbook.add_format({
            'border': 1
        })

        shutdown_fmt = workbook.add_format({
            'bg_color': '#F8CBAD',  # แดงอ่อน
            'border': 1
        })

        center_fmt = workbook.add_format({
            'align': 'center',
            'border': 1
        })

        wrap_fmt = workbook.add_format({
            'text_wrap': True,
            'border': 1
        })

        # ------------------------
        # Header formatting
        # ------------------------
        for col_num, col_name in enumerate(pd.DataFrame(iface_list).columns):
            worksheet.write(0, col_num, col_name, header_fmt)

        # ------------------------
        # Column width
        # ------------------------
        worksheet.set_column('A:A', 12)   # Port
        worksheet.set_column('B:B', 22)   # Description
        worksheet.set_column('C:C', 10)   # Role
        worksheet.set_column('D:F', 14)   # VLANs
        worksheet.set_column('G:G', 25)   # Allowed VLANs
        worksheet.set_column('H:H', 10)   # LAG
        worksheet.set_column('I:I', 10)   # Shutdown

        # ------------------------
        # Freeze header
        # ------------------------
        worksheet.freeze_panes(1, 0)

        # ------------------------
        # Auto Filter
        # ------------------------
        worksheet.autofilter(
            0, 0,
            len(iface_list),
            len(iface_list[0]) - 1
        )

        # ------------------------
        # Row formatting by Role
        # ------------------------
        for row_idx, row in enumerate(iface_list, start=1):
            role = row['Role']
            shutdown = row['Shutdown']

            if shutdown == 'Yes':
                fmt = shutdown_fmt
            elif role == 'access':
                fmt = access_fmt
            elif role == 'trunk':
                fmt = trunk_fmt
            else:
                fmt = default_fmt

            worksheet.set_row(row_idx, None, fmt)


        # Save & Return Bytes
        writer.close()
        output.seek(0)
        return output.read()
    

# ================= PARSER (EXCEL) 🆕 =================
    def _parse_excel(self):
        # อ่านไฟล์ Excel จาก Memory (Bytes)
        # ต้องแน่ใจว่า input_data ถูกส่งมาเป็น bytes (read() จาก file upload)
        xls = pd.ExcelFile(io.BytesIO(self.input_data))

        # 1. Sheet: Global
        if 'Global' in xls.sheet_names:
            df_global = pd.read_excel(xls, 'Global')
            # แปลงเป็น Dict: {'Hostname': 'SW1', 'Banner': '...'}
            global_map = dict(zip(df_global['Parameter'], df_global['Value']))
            
            if 'Hostname' in global_map:
                self.data["hostname"] = str(global_map['Hostname'])
            if 'Banner' in global_map:
                self.data["banner"] = str(global_map['Banner'])

        # 2. Sheet: VLANs
        if 'VLANs' in xls.sheet_names:
            df_vlan = pd.read_excel(xls, 'VLANs').fillna('')
            for _, row in df_vlan.iterrows():
                try:
                    vid = int(row['ID'])
                    self.data["vlans"][vid] = {
                        "name": str(row['Name']),
                        "ip": str(row['IPv4']),
                        "mask": str(row['Mask']),
                        "ipv6": str(row['IPv6'])
                    }
                except: continue

        # 3. Sheet: Interfaces
        if 'Interfaces' in xls.sheet_names:
            df_int = pd.read_excel(xls, 'Interfaces').fillna('')
            for _, row in df_int.iterrows():
                raw_port = str(row['Port'])
                
                # รองรับ Range เช่น "1/1/1-1/1/24"
                ports = self._expand_port_range(raw_port)
                
                for port in ports:
                    # Map Role
                    role = str(row['Role']).lower().strip()
                    mode = None
                    lag_id = None
                    
                    if role == 'access': mode = 'access'
                    elif role == 'trunk': mode = 'trunk'
                    elif role == 'lag_member': 
                        mode = 'lag_member'
                        if row['LAG_ID']: lag_id = str(int(row['LAG_ID']))

                    # VLANs
                    acc_vlan = int(row['Access_VLAN']) if row['Access_VLAN'] else 1
                    nat_vlan = int(row['Native_VLAN']) if row['Native_VLAN'] else 1
                    
                    # Allowed VLANs (แยกด้วย comma)
                    allowed = set()
                    if row['Allowed_VLANs']:
                        for v in str(row['Allowed_VLANs']).split(','):
                            if v.strip().isdigit(): allowed.add(int(v))

                    shutdown = str(row['Shutdown']).lower() == 'yes'

                    self.data["interfaces"][port] = {
                        "description": str(row['Description']),
                        "role": mode,
                        "access_vlan": acc_vlan,
                        "native_vlan": nat_vlan,
                        "allowed_vlans": allowed,
                        "lag_id": lag_id,
                        "shutdown": shutdown
                    }

        # 4. Sheet: Routes
        if 'Routes' in xls.sheet_names:
            df_route = pd.read_excel(xls, 'Routes').fillna('')
            for _, row in df_route.iterrows():
                self.data["routes"].append({
                    "dest": str(row['Destination']),
                    "mask": str(row['Mask']),
                    "next_hop": str(row['Next_Hop'])
                })

    # Helper: ขยาย Range พอร์ต (1/1/1-1/1/5 -> [1/1/1, 1/1/2...])
    def _expand_port_range(self, port_str):
        if '-' not in port_str: return [port_str]
        
        try:
            start_p, end_p = port_str.split('-')
            # สมมติ format เป็น member/slot/num (เช่น 1/1/1)
            prefix = start_p.rsplit('/', 1)[0] # 1/1
            s_num = int(start_p.rsplit('/', 1)[1]) # 1
            e_num = int(end_p.rsplit('/', 1)[1])   # 5
            
            return [f"{prefix}/{i}" for i in range(s_num, e_num + 1)]
        except:
            return [port_str] # ถ้า format แปลกๆ ให้คืนค่าเดิม
        


    # ================= PARSER: HPE COMWARE =================
    def _parse_comware(self):
        # (โค้ดเดิมของ Comware ... ไม่ต้องแก้)
        m = re.search(r"sysname\s+(\S+)", self.raw_log)
        if m: self.data["hostname"] = m.group(1)

        banner_m = re.search(r"header legal\s+(.)(.*?)\1", self.raw_log, re.DOTALL)
        if banner_m: self.data["banner"] = banner_m.group(2).strip()

        # VLANs
        vlan_blocks = re.findall(r"^vlan (\d+)(.*?)(?=^vlan |\n#)", self.raw_log, re.DOTALL | re.MULTILINE)
        for vid, content in vlan_blocks:
            vid = int(vid)
            self.data["vlans"][vid] = {"name": f"VLAN_{vid}", "ip": "", "mask": "", "ipv6": ""}
            d = re.search(r"description\s+(.+)", content)
            if d: self.data["vlans"][vid]["name"] = d.group(1).strip()

        # Interfaces
        interfaces = re.findall(r"^interface ([^\n]+)\n(.*?)(?=\n#)", self.raw_log, re.DOTALL | re.MULTILINE)
        for raw_name, cfg in interfaces:
            if "Vlan-interface" in raw_name: continue
            port = self._map_interface_name(raw_name)
            if not port: continue

            iface = self._init_interface_data(cfg)
            d = re.search(r"description\s+(.+)", cfg)
            if d: iface["description"] = d.group(1).strip()

            # LAG Member
            m = re.search(r"port link-aggregation group (\d+)", cfg)
            if m:
                iface["role"] = "lag_member"
                iface["lag_id"] = m.group(1)
                self.data["interfaces"][port] = iface
                continue

            # Access & Trunk Logic (Comware)
            m = re.search(r"port access vlan (\d+)", cfg)
            if m:
                iface["role"] = "access"
                iface["access_vlan"] = int(m.group(1))

            if "port link-type trunk" in cfg:
                iface["role"] = "trunk"
                m = re.search(r"port trunk pvid vlan (\d+)", cfg)
                iface["native_vlan"] = int(m.group(1)) if m else 1
                m = re.search(r"port trunk permit vlan (.+)", cfg)
                if m: iface["allowed_vlans"] = self._parse_vlan_list(m.group(1))

            self.data["interfaces"][port] = iface

        # SVI
        svis = re.findall(r"^interface Vlan-interface(\d+)\n(.*?)(?=\n#)", self.raw_log, re.DOTALL | re.MULTILINE)
        for vid, cfg in svis:
            self._parse_svi_ip(int(vid), cfg)

        # Routes
        routes = re.findall(r"ip route-static (\S+) (\S+) (\S+)", self.raw_log)
        for d, m, nh in routes: self.data["routes"].append({"dest": d, "mask": m, "next_hop": nh})

    # ================= PARSER: CISCO IOS (เพิ่มใหม่) =================
    def _parse_cisco_ios(self):
        # Hostname
        m = re.search(r"^hostname\s+(\S+)", self.raw_log, re.MULTILINE)
        if m: self.data["hostname"] = m.group(1)

        # Banner
        banner_m = re.search(r"^banner motd\s+(.)(.*?)\1", self.raw_log, re.DOTALL | re.MULTILINE)
        if banner_m: self.data["banner"] = banner_m.group(2).strip()

        # VLAN Definitions (Cisco doesn't always show vlan config block if default)
        vlan_blocks = re.findall(r"^vlan (\d+)\n(.*?)(?=^vlan |^interface |^!)", self.raw_log, re.DOTALL | re.MULTILINE)
        for vid, content in vlan_blocks:
            vid = int(vid)
            self.data["vlans"][vid] = {"name": f"VLAN_{vid}", "ip": "", "mask": "", "ipv6": ""}
            d = re.search(r"name\s+(\S+)", content)
            if d: self.data["vlans"][vid]["name"] = d.group(1).strip()

        # Interfaces
        interfaces = re.findall(r"^interface ([^\n]+)\n(.*?)(?=^interface |^!)", self.raw_log, re.DOTALL | re.MULTILINE)
        for raw_name, cfg in interfaces:
            # Skip SVI here
            if raw_name.lower().startswith("vlan"): continue
            
            port = self._map_interface_name(raw_name)
            if not port: continue

            iface = self._init_interface_data(cfg)
            d = re.search(r"description\s+(.+)", cfg)
            if d: iface["description"] = d.group(1).strip()

            # LAG Member (channel-group 1 mode active)
            m = re.search(r"channel-group (\d+)", cfg)
            if m:
                iface["role"] = "lag_member"
                iface["lag_id"] = m.group(1)
                self.data["interfaces"][port] = iface
                continue

            # Switchport Mode
            mode_match = re.search(r"switchport mode (access|trunk)", cfg)
            mode = mode_match.group(1) if mode_match else "access" # Cisco default access usually
            
            # Check explicit trunk keywords
            if "switchport trunk" in cfg: mode = "trunk"

            if mode == "access":
                iface["role"] = "access"
                m = re.search(r"switchport access vlan (\d+)", cfg)
                iface["access_vlan"] = int(m.group(1)) if m else 1
            
            elif mode == "trunk":
                iface["role"] = "trunk"
                m = re.search(r"switchport trunk native vlan (\d+)", cfg)
                iface["native_vlan"] = int(m.group(1)) if m else 1
                
                m = re.search(r"switchport trunk allowed vlan ([\d,-]+)", cfg)
                if m: iface["allowed_vlans"] = self._parse_vlan_list(m.group(1))

            self.data["interfaces"][port] = iface

        # SVI (Interface Vlan)
        svis = re.findall(r"^interface Vlan(\d+)\n(.*?)(?=^interface |^!)", self.raw_log, re.DOTALL | re.MULTILINE)
        for vid, cfg in svis:
            self._parse_svi_ip(int(vid), cfg)

        # Routes
        routes = re.findall(r"^ip route (\S+) (\S+) (\S+)", self.raw_log, re.MULTILINE)
        for d, m, nh in routes: self.data["routes"].append({"dest": d, "mask": m, "next_hop": nh})

    # ================= SHARED HELPERS =================
    def _init_interface_data(self, cfg):
        return {
            "description": "", "role": None, "access_vlan": 1, 
            "native_vlan": 1, "allowed_vlans": set(), "lag_id": None,
            "shutdown": "shutdown" in cfg
        }

    def _parse_vlan_list(self, vlan_str):
        """ แปลง '1,10,20-30' เป็น set {1, 10, 20, 21...} """
        vids = set()
        for part in vlan_str.split(','):
            part = part.strip()
            if '-' in part:
                s, e = map(int, part.split('-'))
                vids.update(range(s, e + 1))
            elif part.isdigit():
                vids.add(int(part))
        return vids

    def _parse_svi_ip(self, vid, cfg):
        self.data["vlans"].setdefault(vid, {"name": f"VLAN_{vid}", "ip": "", "mask": "", "ipv6": ""})
        m = re.search(r"ip address (\d+\.\d+\.\d+\.\d+) (\d+\.\d+\.\d+\.\d+)", cfg)
        if m:
            self.data["vlans"][vid]["ip"] = m.group(1)
            self.data["vlans"][vid]["mask"] = m.group(2)
        m6 = re.search(r"ipv6 address ([0-9a-fA-F:]+/\d+)", cfg)
        if m6:
            self.data["vlans"][vid]["ipv6"] = m6.group(1)

    def _map_interface_name(self, name):
        name = name.strip()
        
        # --- HPE Comware ---
        # Ten-GigabitEthernet1/1/1 -> 1/2/1
        m = re.match(r"Ten-GigabitEthernet(\d+)/(\d+)/(\d+)", name)
        if m: return f"{m.group(1)}/{int(m.group(2))+1}/{m.group(3)}"
        
        # GigabitEthernet1/0/1 -> 1/1/1
        m = re.match(r"GigabitEthernet(\d+)/(\d+)/(\d+)", name)
        if m: return f"{m.group(1)}/{int(m.group(2))+1}/{m.group(3)}"

        # --- Cisco IOS (2960/Catalyst) ---
        # FastEthernet0/1 -> 1/1/1
        # GigabitEthernet0/1 -> 1/1/25 (สมมติว่าเป็น Uplink ต่อจาก Fa 24 ช่อง)
        # หรือถ้าเป็น Stack: Gi1/0/1 -> 1/1/1
        
        m = re.match(r"(FastEthernet|GigabitEthernet|TenGigabitEthernet)(\d+)/(\d+)", name)
        if m:
            # Cisco Standalone (0/1) or Stack Member (1/0/1)
            # กรณี 0/1 (Stack Member 0 -> 1, Slot 1)
            member = "1"
            slot = "1"
            port = m.group(3)
            
            # ถ้า Input มาเป็นแบบ Stack (1/0/1) ให้ดึงเลข Member มา
            # แต่ Regex ข้างบนจับแค่ 2 กลุ่มตัวเลข ดังนั้นสำหรับ Cisco 2960 (Fa0/1)
            # group(2)=0, group(3)=1
            
            return f"1/1/{port}" # Map ง่ายๆ ไป Slot 1 หมดก่อน

        # LAG
        if name.startswith("Bridge-Aggregation") or name.startswith("Port-channel"):
            # ดึงเลขออกมา
            num = re.search(r"(\d+)$", name)
            return f"lag{num.group(1)}" if num else "lag1"

        return None

    def _iface_sort_key(self, name):
        if name.startswith("lag"):
            return (0, 0, 0, int(name.replace("lag", "")))
        try:
            parts = name.split("/")
            return (1, int(parts[0]), int(parts[1]), int(parts[2]))
        except:
            return (9, 0, 0, 0)

    # ================= GENERATOR (Aruba CX Ready-to-Paste) =================
    def _generate_aruba_cx_ready_to_paste(self):
        lines = []
        lines.append("configure terminal")
        lines.append("")
        lines.append(f"hostname {self.data['hostname']}")
        
        if self.data["banner"]:
            lines.append("banner motd #")
            lines.append(self.data["banner"])
            lines.append("#")
        lines.append("#")

        # VLANs
        for vid in sorted(self.data["vlans"]):
            v = self.data["vlans"][vid]
            lines.append(f"vlan {vid}")
            lines.append(f'    name "{v["name"]}"')
            lines.append("    exit")
        lines.append("#")

        # SVI
        for vid in sorted(self.data["vlans"]):
            v = self.data["vlans"][vid]
            if v["ip"] or v["ipv6"]:
                lines.append(f"interface vlan {vid}")
                if v["ip"]: lines.append(f"    ip address {v['ip']} {v['mask']}")
                if v["ipv6"]: lines.append(f"    ipv6 address {v['ipv6']}")
                lines.append("    exit")
                lines.append("#")

        # LAGs
        lags = set()
        for iface in self.data["interfaces"].values():
            if iface["lag_id"]: lags.add(iface["lag_id"])
        
        for lag_id in sorted(lags, key=lambda x: int(x)):
            lines.append(f"interface lag {lag_id}")
            lines.append("    no shutdown")
            lines.append("    no routing")
            lines.append("    lacp mode active")
            lines.append("    vlan trunk native 1") # Default safe
            lines.append("    vlan trunk allowed all") # Default safe
            lines.append("    exit")
            lines.append("#")

        # Physical Ports (Grouping)
        phy_ports = [p for p in self.data["interfaces"] if not p.startswith("lag")]
        phy_ports.sort(key=self._iface_sort_key)

        groups = []
        if phy_ports:
            current_group = [phy_ports[0]]
            for i in range(1, len(phy_ports)):
                prev, curr = phy_ports[i-1], phy_ports[i]
                prev_conf = self.data["interfaces"][prev]
                curr_conf = self.data["interfaces"][curr]
                
                is_same = (
                    prev_conf["role"] == curr_conf["role"] and
                    prev_conf["access_vlan"] == curr_conf["access_vlan"] and
                    prev_conf["native_vlan"] == curr_conf["native_vlan"] and
                    prev_conf["allowed_vlans"] == curr_conf["allowed_vlans"] and
                    prev_conf["lag_id"] == curr_conf["lag_id"] and
                    prev_conf["shutdown"] == curr_conf["shutdown"]
                )
                
                # Check Consecutive (1/1/1 -> 1/1/2)
                is_cons = False
                try:
                    p = list(map(int, prev.split("/")))
                    c = list(map(int, curr.split("/")))
                    if p[0]==c[0] and p[1]==c[1] and c[2]==p[2]+1: is_cons = True
                except: pass

                if is_same and is_cons: current_group.append(curr)
                else:
                    groups.append(current_group)
                    current_group = [curr]
            groups.append(current_group)

        for group in groups:
            if not group: continue
            first = group[0]
            conf = self.data["interfaces"][first]
            
            header = f"interface {group[0]}" if len(group)==1 else f"interface {group[0]}-{group[-1]}"
            lines.append(header)
            lines.append("    shutdown" if conf["shutdown"] else "    no shutdown")
            
            if len(group) == 1 and conf["description"]:
                lines.append(f"    description {conf['description']}")

            if conf["role"] == "lag_member":
                lines.append(f"    lag {conf['lag_id']}")
            elif conf["role"] == "access":
                lines.append(f"    vlan access {conf['access_vlan']}")
            elif conf["role"] == "trunk":
                lines.append(f"    vlan trunk native {conf['native_vlan']}")
                allowed = sorted([v for v in conf["allowed_vlans"] if v != conf["native_vlan"]])
                if allowed: lines.append(f"    vlan trunk allowed {','.join(map(str, allowed))}")
            
            lines.append("    exit")
            lines.append("#")

        for r in self.data["routes"]:
            lines.append(f"ip route {r['dest']} {r['mask']} {r['next_hop']}")

        lines.append("end")
        lines.append("write memory")
        
        return "\n".join(lines)