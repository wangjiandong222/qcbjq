from __future__ import annotations

from dataclasses import dataclass


MODULE_PUBLIC_INTEREST = "public_interest"
MODULE_VULNERABLE = "vulnerable"
MODULE_ADMINISTRATIVE = "administrative"

MODULE_LABELS = {
    MODULE_PUBLIC_INTEREST: "公益成案领域",
    MODULE_VULNERABLE: "弱势群体",
    MODULE_ADMINISTRATIVE: "行政违法",
}

PUBLIC_INTEREST_UNKNOWN = "未知领域"
VULNERABLE_UNKNOWN = "其他"
ADMINISTRATIVE_UNKNOWN = "其他"


@dataclass(frozen=True)
class Rule:
    name: str
    module: str
    domain: str
    keywords: tuple[str, ...]
    weight: float = 1.0


DEFAULT_RULES: list[Rule] = [
    Rule("生态环境和资源保护", MODULE_PUBLIC_INTEREST, "生态环境和资源保护", ("偷排", "废水", "黑臭", "排污", "油烟", "扬尘", "噪声", "扰民噪音", "渣土", "废气", "河道", "异味", "垃圾堆放", "污染", "水污染", "空气污染", "露天焚烧", "毁林", "采砂", "水源地"), 1.15),
    Rule("食品药品安全", MODULE_PUBLIC_INTEREST, "食品药品安全", ("食品", "食品安全", "药品", "过期", "过期食品", "三无", "吃坏肚子", "拉肚子", "腹泻", "食物中毒", "蟑螂", "无证", "食源性", "变质", "变质食品", "假药", "保健品", "餐饮卫生", "外卖卫生"), 1.15),
    Rule("国有财产保护", MODULE_PUBLIC_INTEREST, "国有财产保护", ("国有资产", "国有财产", "财政资金", "专项资金", "补贴资金", "骗补", "资产流失", "公共资金"), 1.0),
    Rule("国有土地使用权出让", MODULE_PUBLIC_INTEREST, "国有土地使用权出让", ("土地出让", "出让金", "闲置土地", "违法用地", "改变土地用途", "未缴土地款", "国有土地"), 1.0),
    Rule("英烈保护", MODULE_PUBLIC_INTEREST, "英烈保护", ("英烈", "烈士", "英雄烈士", "纪念设施", "烈士陵园", "侮辱烈士", "诋毁英烈"), 1.0),
    Rule("未成年人保护", MODULE_PUBLIC_INTEREST, "未成年人保护", ("未成年人", "学生", "孩子", "校园", "网吧", "烟酒", "儿童", "校外培训", "游戏厅", "校园周边", "未成年"), 1.0),
    Rule("军人地位和权益保障", MODULE_PUBLIC_INTEREST, "军人地位和权益保障", ("军人", "退役军人", "军属", "烈属", "军人权益", "优抚", "抚恤"), 1.0),
    Rule("安全生产", MODULE_PUBLIC_INTEREST, "安全生产", ("消防", "井盖", "塌陷", "燃气", "燃气泄漏", "安全隐患", "重大隐患", "通道堵塞", "消防通道", "工地安全", "危化", "电动车", "飞线充电", "高空坠物", "坍塌", "生产安全"), 1.1),
    Rule("个人信息保护", MODULE_PUBLIC_INTEREST, "个人信息保护", ("个人信息", "泄露", "骚扰电话", "违规收集", "隐私", "人脸识别", "买卖信息", "验证码", "账号被盗"), 1.0),
    Rule("反电信网络诈骗", MODULE_PUBLIC_INTEREST, "反电信网络诈骗", ("电信诈骗", "网络诈骗", "刷单", "杀猪盘", "冒充客服", "诈骗电话", "涉诈", "反诈", "养老诈骗"), 1.0),
    Rule("无障碍环境建设", MODULE_PUBLIC_INTEREST, "无障碍环境建设", ("无障碍", "盲道", "轮椅", "残疾人", "坡道", "电梯故障", "扶手", "占用盲道"), 1.0),
    Rule("文物和文化遗产保护", MODULE_PUBLIC_INTEREST, "文物和文化遗产保护", ("文物", "古树", "古建", "文化遗产", "保护碑", "历史建筑", "古迹", "非遗"), 1.0),
    Rule("农产品质量安全", MODULE_PUBLIC_INTEREST, "农产品质量安全", ("农产品", "农药残留", "兽药残留", "农资", "种子", "化肥", "农产品质量", "蔬菜检测"), 1.0),
    Rule("野生动物保护", MODULE_PUBLIC_INTEREST, "野生动物保护", ("野生动物", "非法捕猎", "捕鸟", "贩卖野生动物", "野鸟", "野生鱼", "保护动物"), 1.0),
    Rule("反垄断", MODULE_PUBLIC_INTEREST, "反垄断", ("垄断", "限定交易", "串通涨价", "价格联盟", "市场支配", "排除竞争", "限制竞争"), 1.0),
    Rule("妇女", MODULE_VULNERABLE, "妇女", ("妇女", "女性", "孕妇", "哺乳期", "女职工", "产假", "性骚扰", "家暴", "离婚纠纷", "抚养费"), 1.1),
    Rule("儿童", MODULE_VULNERABLE, "儿童", ("儿童", "孩子", "未成年人", "学生", "幼儿", "监护", "抚养", "校园欺凌", "辍学", "托育"), 1.1),
    Rule("残疾人", MODULE_VULNERABLE, "残疾人", ("残疾人", "残障", "残疾证", "无障碍", "轮椅", "听障", "视障", "精神障碍", "残疾补贴"), 1.1),
    Rule("老人", MODULE_VULNERABLE, "老人", ("老人", "老年人", "高龄", "养老", "赡养", "独居", "养老金", "养老院", "护理", "遗弃"), 1.1),
    Rule("农民工", MODULE_VULNERABLE, "农民工", ("农民工", "务工人员", "工友", "工资", "欠薪", "讨薪", "包工头", "工钱", "劳务费", "班组", "工地"), 1.2),
    Rule("小过重罚", MODULE_ADMINISTRATIVE, "小过重罚", ("处罚过重", "罚款过重", "小过重罚", "过罚不当", "首违", "轻微违法", "免罚", "警告", "自由裁量"), 1.15),
    Rule("同案不同罚", MODULE_ADMINISTRATIVE, "同案不同罚", ("同案不同罚", "一样情况", "处罚不一样", "标准不一", "区别对待", "执法不公"), 1.1),
    Rule("证据不足处罚", MODULE_ADMINISTRATIVE, "证据不足处罚", ("证据不足", "没有证据", "事实不清", "未查清", "认定错误", "凭空处罚"), 1.1),
    Rule("未告知权利处罚", MODULE_ADMINISTRATIVE, "未告知权利处罚", ("未告知权利", "没有告知", "陈述申辩", "听证权利", "未送达", "权利义务告知"), 1.1),
    Rule("未按程序处罚", MODULE_ADMINISTRATIVE, "未按程序处罚", ("程序违法", "未按程序", "程序不规范", "先罚后告知", "未立案", "未调查", "未听取申辩"), 1.1),
    Rule("选择性执法", MODULE_ADMINISTRATIVE, "选择性执法", ("选择性执法", "只罚我", "别人不罚", "针对我", "执法不公", "区别执法"), 1.05),
    Rule("重复处罚", MODULE_ADMINISTRATIVE, "重复处罚", ("重复处罚", "再次处罚", "已经罚过", "一事二罚", "同一事项又罚"), 1.05),
    Rule("裁量失当处罚", MODULE_ADMINISTRATIVE, "裁量失当处罚", ("裁量失当", "自由裁量", "处罚幅度", "畸重", "明显不当", "裁量基准"), 1.05),
    Rule("未考虑从轻情节处罚", MODULE_ADMINISTRATIVE, "未考虑从轻情节处罚", ("从轻", "减轻", "主动整改", "首次违法", "危害轻微", "没有考虑", "整改完成"), 1.05),
    Rule("以罚代管", MODULE_ADMINISTRATIVE, "以罚代管", ("以罚代管", "只罚不管", "罚完不整改", "只收罚款", "监管不到位"), 1.05),
]

PUBLIC_INTEREST_TERMS = ("大家", "居民", "多人", "好多", "不特定", "公共", "孩子", "村民", "群众", "整栋楼", "附近")


def seed_rule_rows() -> list[dict]:
    return [
        {"name": rule.name, "module": rule.module, "domain": rule.domain, "keywords": ",".join(rule.keywords), "weight": rule.weight, "enabled": True}
        for rule in DEFAULT_RULES
    ]
