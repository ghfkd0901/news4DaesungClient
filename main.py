import streamlit as st
import requests
import html
import pandas as pd
import re
import time
from collections import defaultdict

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="대성에너지 뉴스 모니터링",
    page_icon="🔥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CSS 스타일링 ---
st.markdown("""
    <style>
        .block-container {padding-top: 1rem;}
        div[data-testid="stTooltipContent"] { 
            font-size: 14px; 
            font-family: 'Pretendard', sans-serif;
        }
        div[data-testid="stVerticalBlock"] a {
            display: block;
            white-space: normal !important;
            overflow-wrap: break-word !important;
            word-break: keep-all !important;
            line-height: 1.4 !important;
            margin-bottom: 5px;
        }
    </style>
""", unsafe_allow_html=True)

# --- 3. 비밀키 로드 ---
try:
    NAVER_ID = st.secrets["NAVER_CLIENT_ID"]
    NAVER_SECRET = st.secrets["NAVER_CLIENT_SECRET"]
    SLACK_URL = st.secrets["SLACK_WEBHOOK_URL"]
except:
    st.error("🚫 설정 파일 오류: secrets.toml 파일을 확인해주세요.")
    st.stop()

# --- 4. 데이터 로드 및 전처리 ---
@st.cache_data(ttl=600)
def load_top_customers_data():
    sheet_id = "1uneDYeTtVztafjrzXGiym94Ux6C0gJEHLkE41_0s4dE"
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        df = pd.read_csv(csv_url)
        if "고객명" in df.columns and "2024년 연사용량" in df.columns:
            df["usage"] = df["2024년 연사용량"].astype(str).str.replace(",", "").apply(pd.to_numeric, errors='coerce').fillna(0)
            df_sorted = df.sort_values(by="usage", ascending=False)
            return df_sorted["고객명"].tolist()
        else:
            return ["한국제지", "대성에너지"]
    except:
        return ["한국제지", "대성에너지"]

def clean_company_name(name):
    name = re.sub(r'\([^)]*\)', '', name)
    name = name.replace("주식회사", "").replace("(주)", "")
    return name.strip()

# --- 5. API 및 슬랙 함수 ---
def get_naver_news(query):
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {"X-Naver-Client-Id": NAVER_ID, "X-Naver-Client-Secret": NAVER_SECRET}
    params = {"query": query, "display": 3, "sort": "date"}
    try:
        res = requests.get(url, headers=headers, params=params)
        return res.json().get('items', []) if res.status_code == 200 else []
    except:
        return []

def send_company_batch(company, news_list):
    blocks = []
    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f"🏢 {company} 주요 소식", "emoji": True}
    })
    blocks.append({"type": "divider"})
    
    for news in news_list[:5]:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*<{news['link']}|{news['title']}>*\n📅 {news['date']}"
            }
        })
    blocks.append({
        "type": "context", 
        "elements": [{"type": "mrkdwn", "text": "From 대성에너지 수요개발팀 뉴스 에이전트"}]
    })
    
    payload = {"text": f"{company} 관련 뉴스 모음", "blocks": blocks}
    requests.post(SLACK_URL, json=payload)

# --- 6. 메인 로직 ---

st.title("🔥 대량 수요처 뉴스 모니터링")

# [데이터 선행 로드]
# 슬라이더의 최대값을 알기 위해 데이터를 먼저 불러옵니다.
full_customer_list = load_top_customers_data()
total_customers = len(full_customer_list)

# [사이드바]
with st.sidebar:
    st.header("⚙️ 검색 설정", help="""
**[🔎 뉴스 수집 원리]**
구글 시트의 전체 고객 리스트를 기반으로 네이버 뉴스 API를 통해 실시간 데이터를 수집합니다.
(주) 등의 법인명을 제외하고, 설정한 키워드가 포함된 기사만 필터링합니다.
""")
    
    # 📢 [요청 반영] 슬라이더 Max값을 총 고객 수로, 기본값(value)도 총 고객 수로 설정
    top_n = st.slider(
        "📊 검색 대상 기업 수", 
        min_value=1, 
        max_value=total_customers, 
        value=total_customers, 
        help=f"총 {total_customers}개의 기업 중 상위 N개를 검색합니다."
    )
    
    filter_word = st.text_input("🔍 키워드 필터", placeholder="예: 화재, 사고", help="쉼표(,)로 구분 시 OR 조건 검색")
    
    st.divider()
    
    if st.button("🔍 뉴스 분석 시작", type="primary", use_container_width=True):
        st.session_state['search_triggered'] = True
        st.session_state['news_results'] = {} 
        
        # 슬라이더에서 선택한 N개만큼 자르기
        target_list = full_customer_list[:top_n]
        results = {}
        
        progress_text = st.empty() 
        bar = st.progress(0)
        
        for idx, raw_name in enumerate(target_list):
            search_name = clean_company_name(raw_name)
            progress_text.text(f"수집 중: {raw_name} ({idx+1}/{len(target_list)})")
            
            if len(search_name) >= 2:
                items = get_naver_news(search_name)
                valid_items = []
                filter_keywords = [k.strip() for k in filter_word.split(',')] if filter_word else []
                
                for item in items:
                    title = html.unescape(item['title'].replace("<b>", "").replace("</b>", ""))
                    desc = html.unescape(item['description'].replace("<b>", "").replace("</b>", ""))
                    
                    if filter_keywords:
                        is_match = False
                        for key in filter_keywords:
                            if key in title or key in desc:
                                is_match = True
                                break
                        if not is_match:
                            continue 
                    
                    valid_items.append({
                        "title": title, "link": item['originallink'] or item['link'],
                        "date": item['pubDate'][:16], "desc": desc
                    })
                
                if valid_items:
                    results[raw_name] = valid_items
            
            bar.progress((idx + 1) / len(target_list))
            time.sleep(0.05)
        
        progress_text.empty()
        bar.empty()
        st.session_state['news_results'] = results

# [메인 화면]
if st.session_state.get('search_triggered') and 'news_results' in st.session_state:
    results = st.session_state['news_results']
    
    if not results:
        st.info("검색 결과가 없습니다.")
    else:
        with st.container(border=True):
            c1, c2 = st.columns([0.15, 0.85])
            with c1:
                global_select = st.checkbox("✅ 전체 선택", value=False)
            with c2:
                st.write(f"**총 {len(results)}개 기업 뉴스 발견**")

        final_selected_items = []

        for company, news_list in results.items():
            with st.container():
                c1, c2 = st.columns([0.03, 0.97])
                with c1:
                    comp_select = st.checkbox(f"all_{company}", key=f"c_{company}", value=global_select, label_visibility="collapsed")
                with c2:
                    st.markdown(f"#### 🏢 {company} <span style='font-size:14px; color:gray'>({len(news_list)}건)</span>", unsafe_allow_html=True)
            
            # 3열 배치 유지
            cols = st.columns(3)
            for i, news in enumerate(news_list):
                with cols[i % 3]:
                    with st.container(border=True):
                        st.markdown(f"**[{news['title']}]({news['link']})**")
                        st.caption(f"{news['date']}")
                        
                        if st.checkbox("선택", key=f"{company}_{i}", value=comp_select):
                            final_selected_items.append((company, news))
            st.markdown("---")

        with st.sidebar:
            st.divider()
            st.subheader("📤 전송 센터")
            st.metric(label="선택된 뉴스", value=f"{len(final_selected_items)} 건")
            
            if len(final_selected_items) > 0:
                if st.button("🚀 선택 항목 Slack 전송", type="primary", use_container_width=True):
                    with st.spinner("전송 중..."):
                        grouped = defaultdict(list)
                        for comp, item in final_selected_items:
                            grouped[comp].append(item)
                        
                        total = len(grouped)
                        for idx, (comp, items) in enumerate(grouped.items()):
                            send_company_batch(comp, items)
                            time.sleep(0.1)
                            
                        st.toast(f"✅ 총 {total}개 회사의 뉴스를 전송했습니다!", icon="🎉")
                        time.sleep(1)
            else:
                st.caption("뉴스를 선택하면 전송 버튼이 나타납니다.")

else:
    st.info("👈 사이드바에서 설정을 확인하고 '뉴스 분석 시작'을 눌러주세요.")