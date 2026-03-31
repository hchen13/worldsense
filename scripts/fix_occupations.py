#!/usr/bin/env python3
"""
fix_occupations.py
- Add CN Chinese titles to all 342 standard occupations
- Fix China salary using piecewise linear mapping
- Clean up "See How to Become One" education entries
- Export updated JSON and CSV
"""

import json
import csv
import shutil
import os

# ── 1. Translation dictionary (342 standard occupations) ──────────────────────
TRANSLATIONS = {
    "Accountants and auditors": "会计与审计师",
    "Actors": "演员",
    "Actuaries": "精算师",
    "Administrative services and facilities managers": "行政与设施管理经理",
    "Adult basic and secondary education and ESL teachers": "成人基础教育及英语教师",
    "Advertising sales agents": "广告销售",
    "Advertising, promotions, and marketing managers": "广告、推广与市场营销经理",
    "Aerospace engineering and operations technologists and technicians": "航空航天工程技术人员",
    "Aerospace engineers": "航空航天工程师",
    "Agricultural and food science technicians": "农业与食品科学技术员",
    "Agricultural and food scientists": "农业与食品科学家",
    "Agricultural engineers": "农业工程师",
    "Agricultural workers": "农业工人",
    "Air traffic controllers": "空中交通管制员",
    "Aircraft and avionics equipment mechanics and technicians": "航空器及航电设备维修技术员",
    "Airline and commercial pilots": "民航飞行员",
    "Animal care and service workers": "动物护理服务人员",
    "Announcers and DJs": "播音员和DJ",
    "Anthropologists and archeologists": "人类学家与考古学家",
    "Arbitrators, mediators, and conciliators": "仲裁员与调解员",
    "Architects": "建筑师",
    "Architectural and engineering managers": "建筑与工程管理经理",
    "Archivists, curators, and museum workers": "档案管理员与博物馆工作者",
    "Art directors": "艺术总监",
    "Assemblers and fabricators": "装配工",
    "Athletes and sports competitors": "职业运动员",
    "Athletic trainers": "运动训练师",
    "Atmospheric scientists, including meteorologists": "大气科学家（含气象学家）",
    "Audiologists": "听力学家",
    "Automotive body and glass repairers": "汽车钣金与玻璃修复工",
    "Automotive service technicians and mechanics": "汽车维修技工",
    "Bakers": "烘焙师",
    "Barbers, hairstylists, and cosmetologists": "理发师和美容师",
    "Bartenders": "调酒师",
    "Bill and account collectors": "账款催收员",
    "Biochemists and biophysicists": "生物化学家与生物物理学家",
    "Bioengineers and biomedical engineers": "生物医学工程师",
    "Biological technicians": "生物技术员",
    "Boilermakers": "锅炉工",
    "Bookkeeping, accounting, and auditing clerks": "会计记账员",
    "Broadcast, sound, and video technicians": "广播、音响与视频技术员",
    "Budget analysts": "预算分析师",
    "Bus drivers": "公交车司机",
    "Butchers": "肉食加工工人",
    "Calibration technologists and technicians": "计量校准技术员",
    "Cardiovascular technologists and technicians": "心血管技术员",
    "Career and technical education teachers": "职业技术教育教师",
    "Carpenters": "木工",
    "Cartographers and photogrammetrists": "制图师与摄影测量师",
    "Cashiers": "收银员",
    "Chefs and head cooks": "大厨",
    "Chemical engineers": "化学工程师",
    "Chemical technicians": "化学技术员",
    "Chemists and materials scientists": "化学家与材料科学家",
    "Childcare workers": "托育服务人员",
    "Chiropractors": "脊椎指压治疗师",
    "Civil engineering technologists and technicians": "土木工程技术员",
    "Civil engineers": "土木工程师",
    "Claims adjusters, appraisers, examiners, and investigators": "理赔员与保险调查员",
    "Clinical laboratory technologists and technicians": "临床检验技师",
    "Coaches and scouts": "教练与球探",
    "Community health workers": "社区卫生工作者",
    "Compensation and benefits managers": "薪酬福利经理",
    "Compensation, benefits, and job analysis specialists": "薪酬福利与岗位分析专员",
    "Compliance officers": "合规专员",
    "Computer and information research scientists": "计算机与信息研究科学家",
    "Computer and information systems managers": "信息系统经理",
    "Computer hardware engineers": "计算机硬件工程师",
    "Computer network architects": "网络架构师",
    "Computer programmers": "程序员",
    "Computer support specialists": "IT技术支持专员",
    "Computer systems analysts": "计算机系统分析师",
    "Concierges": "礼宾员",
    "Conservation scientists and foresters": "自然保护科学家与林业员",
    "Construction and building inspectors": "建筑质检员",
    "Construction equipment operators": "工程机械操作员",
    "Construction laborers and helpers": "建筑工人",
    "Construction managers": "施工管理经理",
    "Cooks": "厨师",
    "Correctional officers and bailiffs": "狱警与法警",
    "Cost estimators": "成本估算师",
    "Court reporters and simultaneous captioners": "法庭速记员",
    "Craft and fine artists": "工艺与纯艺术家",
    "Credit counselors": "信贷顾问",
    "Customer service representatives": "客服",
    "Dancers and choreographers": "舞蹈演员与编舞",
    "Data scientists": "数据科学家",
    "Database administrators and architects": "数据库管理员与架构师",
    "Delivery truck drivers and driver/sales workers": "货运司机与送货员",
    "Dental and ophthalmic laboratory technicians and medical appliance technicians": "口腔与眼科技术员",
    "Dental assistants": "口腔助理",
    "Dental hygienists": "口腔卫生士",
    "Dentists": "牙医",
    "Desktop publishers": "桌面排版专员",
    "Diagnostic medical sonographers": "超声诊断师",
    "Diesel service technicians and mechanics": "柴油机维修技工",
    "Dietitians and nutritionists": "营养师",
    "Drafters": "制图员",
    "Drywall installers, ceiling tile installers, and tapers": "石膏板安装与吊顶工",
    "Economists": "经济学家",
    "Editors": "编辑",
    "Electrical and electronic engineering technologists and technicians": "电气与电子工程技术员",
    "Electrical and electronics engineers": "电气工程师",
    "Electrical and electronics installers and repairers": "电气设备安装维修工",
    "Electrical power-line installers and repairers": "电力线路安装维修工",
    "Electricians": "电工",
    "Electro-mechanical and mechatronics technologists and technicians": "机电技术员",
    "Elementary, middle, and high school principals": "中小学校长",
    "Elevator and escalator installers and repairers": "电梯安装维修工",
    "Emergency management directors": "应急管理指挥官",
    "EMTs and paramedics": "急救医疗技术员",
    "Entertainment and recreation managers": "娱乐休闲场所经理",
    "Environmental engineering technologists and technicians": "环境工程技术员",
    "Environmental engineers": "环境工程师",
    "Environmental science and protection technicians": "环保科学技术员",
    "Environmental scientists and specialists": "环境科学家与专家",
    "Epidemiologists": "流行病学家",
    "Exercise physiologists": "运动生理学家",
    "Farmers, ranchers, and other agricultural managers": "农民与农场经营者",
    "Fashion designers": "服装设计师",
    "Film and video editors and camera operators": "影视剪辑师与摄影师",
    "Financial analysts": "金融分析师",
    "Financial clerks": "财务文员",
    "Financial examiners": "金融审查员",
    "Financial managers": "财务总监",
    "Fire inspectors": "消防检查员",
    "Firefighters": "消防员",
    "Fishing and hunting workers": "渔民与猎人",
    "Fitness trainers and instructors": "健身教练",
    "Flight attendants": "空乘",
    "Flooring installers and tile and stone setters": "地板及瓷砖铺装工",
    "Floral designers": "花艺设计师",
    "Food and beverage serving and related workers": "餐饮服务人员",
    "Food preparation workers": "餐饮备餐工",
    "Food processing equipment workers": "食品加工机械操作工",
    "Food service managers": "餐饮经理",
    "Forensic science technicians": "法医技术员",
    "Forest and conservation workers": "林业与生态保护工作者",
    "Fundraisers": "募款专员",
    "Funeral service workers": "殡仪服务人员",
    "Gambling services workers": "博彩服务人员",
    "General maintenance and repair workers": "综合维修工",
    "General office clerks": "普通文员",
    "Genetic counselors": "遗传咨询师",
    "Geographers": "地理学家",
    "Geological and hydrologic technicians": "地质与水文技术员",
    "Geoscientists": "地球科学家",
    "Glaziers": "玻璃工",
    "Graphic designers": "平面设计师",
    "Grounds maintenance workers": "绿化维护工",
    "Hand laborers and material movers": "搬运工",
    "Hazardous materials removal workers": "危险品处置工",
    "Health and safety engineers": "健康安全工程师",
    "Health education specialists": "健康教育专家",
    "Health information technologists and medical registrars": "医疗信息技术员",
    "Heating, air conditioning, and refrigeration mechanics and installers": "暖通空调维修技工",
    "Heavy and tractor-trailer truck drivers": "重型卡车司机",
    "Heavy vehicle and mobile equipment service technicians": "重型机械维修技工",
    "High school teachers": "高中教师",
    "Historians": "历史学家",
    "Home health and personal care aides": "家政护理人员",
    "Human resources managers": "人力资源经理",
    "Human resources specialists": "人力资源专员",
    "Hydrologists": "水文学家",
    "Industrial designers": "工业设计师",
    "Industrial engineering technologists and technicians": "工业工程技术员",
    "Industrial engineers": "工业工程师",
    "Industrial machinery mechanics, machinery maintenance workers, and millwrights": "工业机械维修工",
    "Industrial production managers": "生产经理",
    "Information clerks": "信息服务文员",
    "Information security analysts": "信息安全分析师",
    "Instructional coordinators": "教学协调员",
    "Insulation workers": "绝热工程工人",
    "Insurance sales agents": "保险销售员",
    "Insurance underwriters": "保险核保员",
    "Interior designers": "室内设计师",
    "Interpreters and translators": "口译与笔译人员",
    "Ironworkers": "铁工",
    "Janitors and building cleaners": "清洁工",
    "Jewelers and precious stone and metal workers": "珠宝首饰工匠",
    "Judges and hearing officers": "法官与裁判员",
    "Kindergarten and elementary school teachers": "幼儿园及小学教师",
    "Labor relations specialists": "劳动关系专员",
    "Landscape architects": "景观设计师",
    "Lawyers": "律师",
    "Librarians and library media specialists": "图书馆员与媒体专员",
    "Library technicians and assistants": "图书馆助理",
    "Licensed practical and licensed vocational nurses": "执业护士（初级）",
    "Loan officers": "贷款专员",
    "Lodging managers": "住宿业经理",
    "Logging workers": "伐木工",
    "Logisticians": "物流工程师",
    "Machinists and tool and die makers": "机械工与模具制造工",
    "Management analysts": "管理咨询顾问",
    "Manicurists and pedicurists": "美甲师",
    "Marine engineers and naval architects": "船舶工程师",
    "Market research analysts": "市场调研分析师",
    "Marriage and family therapists": "婚姻与家庭咨询师",
    "Masonry workers": "砌筑工",
    "Massage therapists": "按摩师",
    "Material moving machine operators": "物料搬运机械操作员",
    "Material recording clerks": "仓储记录文员",
    "Materials engineers": "材料工程师",
    "Mathematicians and statisticians": "数学家与统计学家",
    "Mechanical engineering technologists and technicians": "机械工程技术员",
    "Mechanical engineers": "机械工程师",
    "Medical and health services managers": "医疗卫生服务经理",
    "Medical assistants": "医疗助理",
    "Medical dosimetrists": "医疗剂量师",
    "Medical equipment repairers": "医疗设备维修员",
    "Medical records specialists": "病历专员",
    "Medical scientists": "医学科研人员",
    "Medical transcriptionists": "医疗文字录入员",
    "Meeting, convention, and event planners": "会议与活动策划师",
    "Metal and plastic machine workers": "金属与塑料机床操作工",
    "Microbiologists": "微生物学家",
    "Middle school teachers": "初中教师",
    "Military careers": "军人",
    "Mining and geological engineers": "采矿与地质工程师",
    "Models": "模特",
    "Music directors and composers": "音乐总监与作曲家",
    "Musicians and singers": "音乐家与歌手",
    "Natural sciences managers": "自然科学研究经理",
    "Network and computer systems administrators": "网络与计算机系统管理员",
    "News analysts, reporters, and journalists": "记者与新闻分析师",
    "Nuclear engineers": "核工程师",
    "Nuclear medicine technologists": "核医学技术员",
    "Nuclear technicians": "核技术员",
    "Nurse anesthetists, nurse midwives, and nurse practitioners": "高级执业护士",
    "Nursing assistants and orderlies": "护理助理",
    "Occupational health and safety specialists and technicians": "职业健康安全专员",
    "Occupational therapists": "职能治疗师",
    "Occupational therapy assistants and aides": "职能治疗助理",
    "Oil and gas workers": "石油天然气工人",
    "Operations research analysts": "运筹学分析师",
    "Opticians": "验光配镜师",
    "Optometrists": "验光师",
    "Orthotists and prosthetists": "矫形器与假肢技师",
    "Painters, construction and maintenance": "建筑油漆工",
    "Painting and coating workers": "喷涂工",
    "Paralegals and legal assistants": "法律助理",
    "Personal financial advisors": "个人理财顾问",
    "Pest control workers": "害虫防治人员",
    "Petroleum engineers": "石油工程师",
    "Pharmacists": "药剂师",
    "Pharmacy technicians": "药房技术员",
    "Phlebotomists": "采血员",
    "Photographers": "摄影师",
    "Physical therapist assistants and aides": "物理治疗助理",
    "Physical therapists": "物理治疗师",
    "Physician assistants": "医师助理",
    "Physicians and surgeons": "医生与外科医生",
    "Physicists and astronomers": "物理学家与天文学家",
    "Plumbers, pipefitters, and steamfitters": "管道工",
    "Podiatrists": "足病医生",
    "Police and detectives": "警察与侦探",
    "Political scientists": "政治学家",
    "Postal service workers": "邮政工作人员",
    "Postsecondary education administrators": "高等院校行政管理人员",
    "Postsecondary teachers": "大学教授",
    "Power plant operators, distributors, and dispatchers": "电厂运营与调度员",
    "Preschool and childcare center directors": "幼儿园园长",
    "Preschool teachers": "幼儿园教师",
    "Private detectives and investigators": "私家侦探",
    "Probation officers and correctional treatment specialists": "缓刑官与矫治专员",
    "Producers and directors": "制片人与导演",
    "Project management specialists": "项目管理专员",
    "Property appraisers and assessors": "房产评估师",
    "Property, real estate, and community association managers": "物业经理",
    "Psychiatric technicians and aides": "精神科护理助理",
    "Psychologists": "心理学家",
    "Public relations and fundraising managers": "公关与募款经理",
    "Public relations specialists": "公关专员",
    "Public safety telecommunicators": "应急通信员",
    "Purchasing managers, buyers, and purchasing agents": "采购经理与采购员",
    "Quality control inspectors": "质检员",
    "Radiation therapists": "放射治疗师",
    "Radiologic and MRI technologists": "放射与磁共振技师",
    "Railroad workers": "铁路工人",
    "Real estate brokers and sales agents": "房产中介",
    "Receptionists": "前台接待",
    "Recreation workers": "娱乐休闲服务人员",
    "Recreational therapists": "娱乐治疗师",
    "Registered nurses": "注册护士",
    "Rehabilitation counselors": "康复辅导员",
    "Respiratory therapists": "呼吸治疗师",
    "Retail sales workers": "零售销售员",
    "Roofers": "屋面工",
    "Sales engineers": "销售工程师",
    "Sales managers": "销售经理",
    "School and career counselors and advisors": "学校心理辅导员与职业顾问",
    "Secretaries and administrative assistants": "秘书与行政助理",
    "Securities, commodities, and financial services sales agents": "证券与金融销售员",
    "Security guards and gambling surveillance officers": "保安",
    "Semiconductor processing technicians": "半导体加工技术员",
    "Set and exhibit designers": "舞台与展览设计师",
    "Sheet metal workers": "钣金工",
    "Skincare specialists": "皮肤护理师",
    "Small engine mechanics": "小型发动机维修工",
    "Social and community service managers": "社区服务机构管理者",
    "Social and human service assistants": "社会服务助理",
    "Social workers": "社会工作者",
    "Sociologists": "社会学家",
    "Software developers, quality assurance analysts, and testers": "软件开发工程师",
    "Solar photovoltaic installers": "太阳能光伏安装工",
    "Special education teachers": "特殊教育教师",
    "Special effects artists and animators": "特效师与动画师",
    "Speech-language pathologists": "言语治疗师",
    "Stationary engineers and boiler operators": "锅炉与固定式机械操作员",
    "Substance abuse, behavioral disorder, and mental health counselors": "心理健康与成瘾咨询师",
    "Surgical assistants and technologists": "手术助手与外科技术员",
    "Survey researchers": "调查研究员",
    "Surveying and mapping technicians": "测量与制图技术员",
    "Surveyors": "测量师",
    "Tax examiners and collectors, and revenue agents": "税务审查员与税务官",
    "Taxi drivers, shuttle drivers, and chauffeurs": "出租车司机与专职司机",
    "Teacher assistants": "教学助理",
    "Technical writers": "技术文档工程师",
    "Telecommunications technicians": "电信技术员",
    "Tellers": "银行柜员",
    "Top executives": "企业高管",
    "Tour and travel guides": "导游",
    "Training and development managers": "培训与发展经理",
    "Training and development specialists": "培训专员",
    "Transportation, storage, and distribution managers": "运输仓储物流经理",
    "Travel agents": "旅行社代理人",
    "Tutors": "家教",
    "Umpires, referees, and other sports officials": "裁判员",
    "Urban and regional planners": "城市与区域规划师",
    "Veterinarians": "兽医",
    "Veterinary assistants and laboratory animal caretakers": "兽医助理与实验动物饲养员",
    "Veterinary technologists and technicians": "兽医技术员",
    "Waiters and waitresses": "餐厅服务员",
    "Water and wastewater treatment plant and system operators": "水处理与污水处理操作员",
    "Water transportation workers": "水运工作者",
    "Web developers and digital designers": "网页开发与数字设计师",
    "Welders, cutters, solderers, and brazers": "焊工",
    "Wholesale and manufacturing sales representatives": "批发与制造业销售代表",
    "Wind turbine technicians": "风力发电机维修技工",
    "Woodworkers": "木工工人",
    "Writers and authors": "作家与文案",
    "Zoologists and wildlife biologists": "动物学家与野生生物学家",
}


# ── 2. China salary piecewise linear mapping ─────────────────────────────────
def us_to_cn_salary(us_salary):
    """Piecewise linear mapping from US salary to Chinese equivalent in CNY."""
    if us_salary <= 0:
        return 0
    # (us_dollars, cn_yuan) anchor points
    anchors = [
        (25000,  36000),   # 低薪服务业
        (35000,  48000),   # 蓝领
        (50000,  72000),   # 中低薪白领
        (70000, 108000),   # 中等白领
        (90000, 150000),   # 中高薪
        (110000, 200000),  # 高薪
        (140000, 280000),  # 高级专业人士
        (180000, 360000),  # 顶级专业人士
        (250000, 500000),  # 医生/高管
    ]
    if us_salary <= anchors[0][0]:
        return anchors[0][1]
    if us_salary >= anchors[-1][0]:
        return anchors[-1][1]
    for i in range(len(anchors) - 1):
        us_lo, cn_lo = anchors[i]
        us_hi, cn_hi = anchors[i + 1]
        if us_lo <= us_salary <= us_hi:
            t = (us_salary - us_lo) / (us_hi - us_lo)
            raw = cn_lo + t * (cn_hi - cn_lo)
            return int(round(raw / 1000) * 1000)
    return 100000  # fallback


# ── IDs of China-specific occupations to leave untouched ─────────────────────
CN_SPECIFIC_IDS = {
    "civil-servant-cn",
    "food-delivery-driver",
    "courier-express",
    "ride-hailing-driver",
    "ecommerce-operator",
    "livestream-seller",
    "small-business-owner",
    "soe-manager",
    "construction-worker-cn",
    "rural-teacher",
    "public-institution-staff",
    "factory-line-worker",
}


def main():
    data_path = os.path.expanduser("~/projects/worldsense/data/occupations.json")
    csv_tmp   = "/tmp/worldsense_occupations_v2.csv"
    csv_out   = os.path.expanduser("~/.openclaw/media/outbox/worldsense_occupations_v2.csv")

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    translated      = 0
    already_had_cn  = 0
    salary_fixed    = 0
    edu_fixed       = 0
    missing_title   = []

    for occ in data:
        oid = occ["id"]
        title = occ["title"]

        # ── Chinese title ─────────────────────────────────────────────────────
        if oid in CN_SPECIFIC_IDS:
            already_had_cn += 1
        else:
            if "title_local" not in occ:
                occ["title_local"] = {}
            if "CN" not in occ["title_local"]:
                cn_name = TRANSLATIONS.get(title)
                if cn_name:
                    occ["title_local"]["CN"] = cn_name
                    translated += 1
                else:
                    missing_title.append(title)
            else:
                already_had_cn += 1

        # ── China salary ──────────────────────────────────────────────────────
        if oid not in CN_SPECIFIC_IDS:
            us_pay = occ.get("median_pay_annual_usd", 0)
            if us_pay and "countries" in occ and "CN" in occ["countries"]:
                new_cn = us_to_cn_salary(us_pay)
                occ["countries"]["CN"]["pay_local"] = new_cn
                salary_fixed += 1

        # ── Education cleanup ─────────────────────────────────────────────────
        if occ.get("entry_education") == "See How to Become One":
            occ["entry_education"] = "Varies"
            edu_fixed += 1

    # ── Write back JSON ───────────────────────────────────────────────────────
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[OK] JSON written: {data_path}")

    # ── Export CSV ────────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(csv_out), exist_ok=True)
    fieldnames = ["id", "title", "title_cn", "category", "soc_code",
                  "median_pay_usd", "cn_pay_cny", "entry_education", "num_jobs_us"]
    with open(csv_tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for occ in data:
            cn_pay = occ.get("countries", {}).get("CN", {}).get("pay_local", "")
            writer.writerow({
                "id":              occ["id"],
                "title":           occ["title"],
                "title_cn":        occ.get("title_local", {}).get("CN", ""),
                "category":        occ.get("category", ""),
                "soc_code":        occ.get("soc_code", ""),
                "median_pay_usd":  occ.get("median_pay_annual_usd", ""),
                "cn_pay_cny":      cn_pay,
                "entry_education": occ.get("entry_education", ""),
                "num_jobs_us":     occ.get("num_jobs_us", ""),
            })
    shutil.copy2(csv_tmp, csv_out)
    print(f"[OK] CSV written: {csv_tmp}")
    print(f"[OK] CSV copied:  {csv_out}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n=== Summary ===")
    print(f"Total occupations:    {len(data)}")
    print(f"Translated (new CN):  {translated}")
    print(f"Already had CN:       {already_had_cn}")
    print(f"CN salaries updated:  {salary_fixed}")
    print(f"Education cleaned:    {edu_fixed}")
    if missing_title:
        print(f"MISSING translations: {len(missing_title)}")
        for t in missing_title:
            print(f"  - {t!r}")

    # ── Sample verification ───────────────────────────────────────────────────
    samples = [
        "software-developers-quality-assurance-analysts-and-testers",
        "accountants-and-auditors",
        "barbers-hairstylists-and-cosmetologists",
        "home-health-and-personal-care-aides",
        "physicians-and-surgeons",
        "cashiers",
        "lawyers",
        "janitors-and-building-cleaners",
        "civil-servant-cn",
        "factory-line-worker",
    ]
    print("\n=== Sample verification ===")
    occ_by_id = {o["id"]: o for o in data}
    for sid in samples:
        occ = occ_by_id.get(sid)
        if occ:
            cn_name = occ.get("title_local", {}).get("CN", "(missing)")
            us_pay  = occ.get("median_pay_annual_usd", 0)
            cn_pay  = occ.get("countries", {}).get("CN", {}).get("pay_local", "?")
            print(f"  {occ['title']}")
            print(f"    CN: {cn_name}  |  US: ${us_pay:,}  →  CN: ¥{cn_pay:,}")


if __name__ == "__main__":
    main()
