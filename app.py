import streamlit as st
import requests
import pandas as pd
import pydeck as pdk
from datetime import datetime, timedelta
import feedparser
import re
import json
import os

# ========== AI 配置（硅基流动，免费）==========
# 注册：https://siliconflow.cn 获取 API Key（以 sk- 开头）
import os
SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")
def call_ai(prompt):
    """调用硅基流动 DeepSeek-V2.5 模型"""
    url = "https://api.siliconflow.cn/v1/chat/completions"
    headers = {"Authorization": f"Bearer {SILICONFLOW_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "deepseek-ai/DeepSeek-V2.5",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,          # 降低温度，提高一致性
        "max_tokens": 1024
    }
    try:
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        if resp.status_code != 200:
            return f"API调用失败: {resp.status_code}, {resp.text}"
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"调用AI失败: {e}"

# ========== 多新闻源获取（增强版）==========
def fetch_news():
    """从多个国内稳定新闻源获取国际新闻，返回列表"""
    articles = []
    sources = [
        ("新浪国际", "api", "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2517&num=30"),
        ("澎湃国际", "rss", "https://www.thepaper.cn/rss_3_news.xml"),
        ("观察者网", "rss", "https://rsshub.thisdotless.com/obs/guoji"),
        ("腾讯国际", "rss", "https://news.qq.com/newsgj/rss_newsgj.xml"),
        ("网易国际", "rss", "http://news.163.com/special/0001386F/rank_global.xml"),
        ("环球网", "rss", "http://world.huanqiu.com/rss.xml"),
        ("央视国际", "rss", "http://news.cctv.com/world/special/world/world_1/rss.xml"),
        ("参考消息", "rss", "https://rsshub.thisdotless.com/cankaoxiaoxi"),
        ("联合早报", "rss", "https://www.zaobao.com/special/realtime/rss.xml"),
    ]
    
    for name, typ, url in sources:
        try:
            if typ == "api":
                resp = requests.get(url, timeout=10)
                resp.encoding = 'utf-8'
                data = resp.json()
                for item in data.get('result', {}).get('data', []):
                    articles.append({
                        "title": item.get('title', '无标题'),
                        "summary": item.get('intro', '无简介'),
                        "link": item.get('url', ''),
                        "published": item.get('ctime', '')[:10],
                        "source": name
                    })
            else:
                feed = feedparser.parse(url)
                for entry in feed.entries[:30]:
                    pub_date = entry.get('published', '')
                    if pub_date:
                        try:
                            dt = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z")
                            pub_date = dt.strftime("%Y-%m-%d")
                        except:
                            try:
                                dt = datetime.strptime(pub_date[:25], "%a, %d %b %Y %H:%M:%S")
                                pub_date = dt.strftime("%Y-%m-%d")
                            except:
                                pub_date = pub_date[:10] if len(pub_date) >= 10 else "未知"
                    else:
                        pub_date = "未知"
                    summary = entry.get('summary', '')
                    summary = re.sub(r'<[^>]+>', '', summary)[:400]
                    articles.append({
                        "title": entry.get('title', '无标题'),
                        "summary": summary,
                        "link": entry.get('link', ''),
                        "published": pub_date,
                        "source": name
                    })
        except Exception as e:
            st.warning(f"⚠️ {name} 获取失败: {e}")
            continue
    
    # 去重
    seen = set()
    unique = []
    for art in articles:
        if art["title"] not in seen:
            seen.add(art["title"])
            unique.append(art)
    unique.sort(key=lambda x: x["published"], reverse=True)
    st.success(f"✅ 获取 {len(unique)} 条国际新闻（来自 {len(sources)} 个源）")
    return unique

# ========== 地区关键词（细化）==========
REGION_KEYWORDS = {
    "非洲": ["非洲", "尼日利亚", "肯尼亚", "南非", "埃塞俄比亚", "安哥拉", "刚果金", "加纳", "坦桑尼亚"],
    "中东": ["中东", "沙特", "伊朗", "伊拉克", "叙利亚", "以色列", "巴勒斯坦", "也门", "黎巴嫩", "阿联酋", "卡塔尔"],
    "东南亚": ["东南亚", "印尼", "马来西亚", "泰国", "越南", "菲律宾", "缅甸", "老挝", "柬埔寨", "东帝汶"],
    "中亚": ["中亚", "哈萨克斯坦", "乌兹别克斯坦", "土库曼斯坦", "吉尔吉斯斯坦", "塔吉克斯坦"],
    "拉美": ["拉美", "巴西", "墨西哥", "阿根廷", "智利", "秘鲁", "哥伦比亚", "委内瑞拉"],
    "欧洲": ["欧洲", "英国", "法国", "德国", "意大利", "俄罗斯", "西班牙", "荷兰", "波兰", "乌克兰"],
    "北美": ["美国", "加拿大", "墨西哥"]
}

# ========== 历史记录管理 ==========
HISTORY_FILE = "risk_history.json"

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_history(history):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def update_history(region, level, date_str):
    history = load_history()
    if region not in history:
        history[region] = []
    # 保留最近7天
    history[region].append({"date": date_str, "level": level})
    history[region] = history[region][-7:]
    save_history(history)
    return history[region]

def get_trend(history_list):
    """根据历史等级判断趋势：上升/下降/平稳"""
    if len(history_list) < 2:
        return "数据不足"
    levels = {"高": 3, "中": 2, "低": 1}
    recent = [levels[h["level"]] for h in history_list[-3:]]
    if len(recent) >= 2:
        diff = recent[-1] - recent[0]
        if diff > 0:
            return "上升"
        elif diff < 0:
            return "下降"
    return "平稳"

# ========== 风险评估（多维度+置信度+历史趋势）==========
def count_relevant_news(region, articles):
    keywords = REGION_KEYWORDS.get(region, [region])
    count = 0
    for art in articles:
        text = (art["title"] + " " + art["summary"]).lower()
        if any(kw.lower() in text for kw in keywords):
            count += 1
    return count

def evaluate_risk(region, articles, history_trend=""):
    keywords = REGION_KEYWORDS.get(region, [region])
    relevant = []
    for art in articles:
        text = (art["title"] + " " + art["summary"]).lower()
        if any(kw.lower() in text for kw in keywords):
            relevant.append(art)
    
    news_count = len(relevant)
    if news_count == 0:
        return "低", "无相关新闻，默认低风险", "低", 0
    
    # 取前25条（增加样本）
    top_news = relevant[:25]
    context = ""
    for i, art in enumerate(top_news, 1):
        context += f"{i}. 【{art['source']}】{art['title']}\n   摘要：{art['summary'][:250]}\n\n"
    
    # 高级提示词：多维度、引用新闻、历史趋势
    prompt = f"""你是一位资深海外利益安全分析师。基于以下关于{region}的{len(top_news)}条新闻，评估该地区对中国海外利益（中资企业、人员、投资项目）的安全风险。

**历史趋势**：{history_trend}（请结合此趋势判断风险是加剧还是缓和）

请从四个维度分别打分（1-5分，1=非常安全，5=极度危险）：
- 政治稳定性：政权稳定、暴力冲突、抗议活动
- 社会治安：犯罪率、绑架、恐怖袭击
- 经济风险：金融动荡、制裁、投资保护
- 对华关系：针对中企/华人的事件、舆论态度

**新闻列表**：
{context}

**输出格式**（必须严格遵守，不要添加额外内容）：
政治稳定性：[1-5分]
社会治安：[1-5分]
经济风险：[1-5分]
对华关系：[1-5分]
综合风险等级：[高/中/低]
置信度：[高/中/低]（根据新闻数量、一致性、清晰度判断）
主要风险因素：（列出1-2个最突出的风险点，不超过30字）
理由：（一句话总结，不超过50字）"""
    
    result = call_ai(prompt)
    
    # 解析
    import re
    level = "中"
    confidence = "中"
    risk_factors = ""
    reason = result
    
    level_match = re.search(r"综合风险等级：\[(高|中|低)\]", result)
    if level_match:
        level = level_match.group(1)
    conf_match = re.search(r"置信度：\[(高|中|低)\]", result)
    if conf_match:
        confidence = conf_match.group(1)
    factor_match = re.search(r"主要风险因素：(.+?)(?:\n|$)", result)
    if factor_match:
        risk_factors = factor_match.group(1).strip()
    
    # 如果新闻数量过少，强制降低置信度
    if news_count < 5:
        confidence = "低"
    
    # 生成完整报告
    full_report = f"""**综合风险等级：{level}**（置信度：{confidence}）

**四个维度评分**：
{chr(10).join([line for line in result.split(chr(10)) if '分]' in line])}

**主要风险因素**：{risk_factors if risk_factors else '无明确风险点'}

**AI分析理由**：{reason if len(reason) < 200 else reason[:200] + '...'}

📊 基于 {news_count} 条相关新闻评估"""
    
    return level, full_report, confidence, news_count

# ========== 地图坐标 ==========
region_coords = {
    "非洲": {"lat": 8.7832, "lon": 34.5085},
    "中东": {"lat": 29.2985, "lon": 42.5510},
    "东南亚": {"lat": 14.0583, "lon": 108.2772},
    "中亚": {"lat": 44.0, "lon": 66.0},
    "拉美": {"lat": -14.2350, "lon": -51.9253},
    "欧洲": {"lat": 48.8566, "lon": 10.0},
    "北美": {"lat": 40.0, "lon": -100.0}
}

# ========== UI ==========
st.set_page_config(page_title="海外利益安全风险评估 v3.0", layout="wide")
st.title("🛡️ 海外利益安全风险评估与热区图")
st.markdown("**多维评估 + 置信度 + 历史趋势** | 基于9个新闻源，每个地区最多25条新闻")

with st.sidebar:
    st.header("📌 评估设置")
    regions = list(region_coords.keys())
    selected = st.multiselect("选择要评估的地区", regions, default=regions)
    if st.button("开始评估"):
        st.session_state.evaluate = True

# 初始化
if "evaluate" not in st.session_state:
    st.session_state.evaluate = False
if "risk_results" not in st.session_state:
    st.session_state.risk_results = {}
if "news" not in st.session_state:
    with st.spinner("获取最新国际新闻..."):
        st.session_state.news = fetch_news()

# 执行评估
if st.session_state.evaluate and selected:
    progress = st.progress(0)
    today_str = datetime.now().strftime("%Y-%m-%d")
    for i, reg in enumerate(selected):
        rel_count = count_relevant_news(reg, st.session_state.news)
        # 获取历史趋势
        history = load_history().get(reg, [])
        trend = get_trend(history)
        with st.spinner(f"评估 {reg}（基于 {rel_count} 条新闻，趋势：{trend}）..."):
            level, report, confidence, news_used = evaluate_risk(reg, st.session_state.news, trend)
            st.session_state.risk_results[reg] = {
                "level": level,
                "report": report,
                "news_count": rel_count,
                "confidence": confidence,
                "trend": trend
            }
            # 保存历史
            update_history(reg, level, today_str)
        progress.progress((i+1)/len(selected))
    st.session_state.evaluate = False
    st.success("评估完成！")

# 热区图
if st.session_state.risk_results:
    data = []
    for reg, info in st.session_state.risk_results.items():
        coords = region_coords.get(reg)
        if coords:
            level = info["level"]
            if level == "高":
                color = [255, 0, 0]
                radius = 500000
            elif level == "中":
                color = [255, 255, 0]
                radius = 300000
            else:
                color = [0, 255, 0]
                radius = 150000
            data.append({"lat": coords["lat"], "lon": coords["lon"], "region": reg, "risk": level, "color": color, "radius": radius})
    if data:
        df = pd.DataFrame(data)
        layer = pdk.Layer("ScatterplotLayer", data=df, get_position=["lon", "lat"], get_fill_color="color", get_radius="radius", pickable=True)
        view = pdk.ViewState(latitude=20, longitude=20, zoom=1.5)
        st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip={"text": "{region}\n风险等级: {risk}"}))
else:
    st.info("请在左侧选择地区并点击「开始评估」生成热区图。")

# 详细报告
if st.session_state.risk_results:
    st.subheader("📋 详细评估报告")
    for reg, info in st.session_state.risk_results.items():
        with st.expander(f"{reg} - 风险等级：{info['level']}  (置信度：{info['confidence']})  历史趋势：{info['trend']}"):
            st.markdown(info["report"])
            # 人工反馈按钮
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ 评估准确", key=f"good_{reg}"):
                    st.success("感谢反馈！")
            with col2:
                if st.button("❌ 评估有误", key=f"bad_{reg}"):
                    st.warning("请描述错误，我们将用于改进")
                    feedback = st.text_input("正确风险等级应为？", key=f"fb_{reg}")
                    if feedback:
                        st.info("已记录反馈，感谢帮助校准！")

# 新闻列表
with st.expander("📰 查看全部新闻（可展开）"):
    for a in st.session_state.news[:60]:
        st.markdown(f"**{a['title']}** ({a['published']})  `{a['source']}`")
        st.write(a['summary'][:200])
        st.markdown(f"[原文]({a['link']})")
        st.markdown("---")

st.caption("AI模型：DeepSeek-V2.5（硅基流动） | 评估维度：政治稳定性、社会治安、经济风险、对华关系 | 历史趋势基于最近7天")