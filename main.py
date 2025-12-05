import streamlit as st
import requests
import html
import pandas as pd
import re
import time
from datetime import datetime
from collections import defaultdict

# --- 1. 페이지 설정 (레이아웃 및 타이틀) ---
st.set_page_config(
    page_title="대성에너지 뉴스 클리핑",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. 고급 UI/UX를 위한 CSS 스타일링 ---
st.markdown("""
    <style>
        /* 전체 폰트 및 가독성 개선 */
        .block-container {
            padding-top: 2rem;
            padding-bottom: 5rem;
            max-width: 1200px;
        }
        
        /* 뉴스 카드 스타일 */
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 12px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
            background-color: white;
        }
        
        /* 뉴스 제목 링크 스타일 */
        .news-link {
            font-size: 16px;
            font-weight: 600;
            color: #2c3e50 !important;
            text-decoration: none;
            line-height: 1.5;
            display: block;
            margin-bottom: 8px;
        }
        .news-link:hover {
            color: #0068c3 !important;
            text-decoration: underline;
        }
        
        /* 날짜 및 부가정보 스타일 */
        .news-date {
            font-size: 12px;
            color: #7f8c8d;
            margin-bottom: 12px;
            display: block;
        }
        
        /* 체크박스 여백 조정 */
        div[data-testid="stCheckbox"] {
            margin-top: 5px;
            margin-bottom: 5px;
        }

        /* 구분선 스타일 */
        hr {
            margin-top: 1rem;
            margin-bottom: 2rem;
            border-color: #eee;
        }
    </style>
""", unsafe_allow_html=True)

# --- 3. 비밀키 로드 ---
try:
    NAVER_ID = st.secrets["NAVER_CLIENT_ID"]
    NAVER_SECRET = st.secrets["NAVER_CLIENT_SECRET"]
    SLACK_URL = st.secrets["SLACK_WEBHOOK_URL"]
except:
    st.error("🚫 설정 파일(secrets.toml)을 확인해주세요.")
    st.stop()

# --- 세션 상태 초기화 ---
if 'news_results' not in st.session_state:
    st.session_state['news_results'] = {}
if 'selected_ids' not in st.session_state:
    st.session_state['selected_ids'] = set()

# --- 4. 유틸리티 함수 ---

def format_slack_date(date_str):
    """슬랙 전송용 날짜 포맷 (yyyy-mm-dd 요일)"""
    if not date_str: return ""
    try:
        dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %z")
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        return f"{dt.strftime('%Y-%m-%d')} ({weekdays[dt.weekday()]})"
    except:
        return date_str[:16]

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
        "text": {"type": "plain_text", "text": f"🏭 {company} 주요 소식", "emoji": True}
    })
    blocks.append({"type": "divider"})
    
    for news in news_list[:5]:
        formatted_date = format_slack_date(news.get('origin_date', news.get('date', '')))
        
        # [수정] 📅(17일 캘린더) 대신 🕒(시계) 이모티콘 사용
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*<{news['link']}|{news['title']}>*\n🕒 {formatted_date}"
            }
        })
    blocks.append({
        "type": "context", 
        "elements": [{"type": "mrkdwn", "text": "From 대성에너지 뉴스 에이전트"}]
    })
    
    payload = {"text": f"{company} 뉴스 모음", "blocks": blocks}
    requests.post(SLACK_URL, json=payload)

# --- 6. 콜백 함수 ---

def toggle_global_check():
    all_keys = set()
    for company, items in st.session_state['news_results'].items():
        for idx, _ in enumerate(items):
            all_keys.add(f"{company}_{idx}")

    if st.session_state.get('global_check'):
        st.session_state['selected_ids'] = all_keys
    else:
        st.session_state['selected_ids'] = set()

def toggle_company_check(company):
    comp_keys = {f"{company}_{i}" for i in range(len(st.session_state['news_results'][company]))}
    if st.session_state.get(f"c_{company}"):
        st.session_state['selected_ids'].update(comp_keys)
    else:
        st.session_state['selected_ids'] -= comp_keys

def toggle_item(unique_key):
    if unique_key in st.session_state['selected_ids']:
        st.session_state['selected_ids'].remove(unique_key)
    else:
        st.session_state['selected_ids'].add(unique_key)

# --- 7. 메인 화면 구성 ---

st.title("📰 대량 수요처 뉴스 모니터링")
st.markdown("<div style='margin-bottom: 30px;'></div>", unsafe_allow_html=True)

full_customer_list = load_top_customers_data()
total_customers = len(full_customer_list)

# [사이드바]
with st.sidebar:
    st.header("🛠️ 검색 옵션")
    st.markdown("---")
    
    top_n = st.slider("📊 검색 대상 기업 수", 1, total_customers, total_customers)
    filter_word = st.text_input("🏷️ 키워드 필터", placeholder="예: 화재, 수주, 폭발")
    
    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    
    if st.button("🔎 뉴스 분석 시작", type="primary", use_container_width=True):
        st.session_state['news_results'] = {}
        st.session_state['selected_ids'] = set()
        
        target_list = full_customer_list[:top_n]
        results = {}
        
        progress_text = st.empty() 
        bar = st.progress(0)
        
        for idx, raw_name in enumerate(target_list):
            search_name = clean_company_name(raw_name)
            progress_text.text(f"📡 수집 중... {raw_name} ({idx+1}/{len(target_list)})")
            
            if len(search_name) >= 2:
                items = get_naver_news(search_name)
                valid_items = []
                filter_keywords = [k.strip() for k in filter_word.split(',')] if filter_word else []
                
                for item in items:
                    title = html.unescape(item['title'].replace("<b>", "").replace("</b>", ""))
                    desc = html.unescape(item['description'].replace("<b>", "").replace("</b>", ""))
                    
                    if filter_keywords:
                        if not any(key in title or key in desc for key in filter_keywords):
                            continue 
                    
                    valid_items.append({
                        "title": title, 
                        "link": item['originallink'] or item['link'],
                        "date": item['pubDate'][:16], 
                        "origin_date": item['pubDate'], 
                        "desc": desc
                    })
                
                if valid_items:
                    results[raw_name] = valid_items
            
            bar.progress((idx + 1) / len(target_list))
            time.sleep(0.05)
        
        progress_text.empty()
        bar.empty()
        st.session_state['news_results'] = results
        st.rerun()

# [메인 콘텐츠]
results = st.session_state['news_results']

if not results:
    st.info("👈 왼쪽 사이드바에서 **[뉴스 분석 시작]** 버튼을 눌러주세요.")
else:
    # --- 컨트롤 패널 ---
    with st.container(border=True):
        c1, c2, c3 = st.columns([0.2, 0.6, 0.2])
        
        with c1:
            total_items = sum(len(v) for v in results.values())
            all_checked = (len(st.session_state['selected_ids']) == total_items) and (total_items > 0)
            st.checkbox("✅ 전체 선택", key="global_check", value=all_checked, on_change=toggle_global_check)
            
        with c2:
            st.markdown(f"<div style='text-align: center; font-size: 1.1em; font-weight: bold;'>🔎 총 {len(results)}개 기업의 관련 뉴스</div>", unsafe_allow_html=True)
            
        with c3:
            count = len(st.session_state['selected_ids'])
            st.markdown(f"<div style='text-align: right; color: #e74c3c; font-weight: bold;'>선택됨: {count}건</div>", unsafe_allow_html=True)

    st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

    # --- 뉴스 리스트 출력 ---
    for company, news_list in results.items():
        with st.container():
            c_head1, c_head2 = st.columns([0.05, 0.95])
            with c_head1:
                comp_ids = {f"{company}_{i}" for i in range(len(news_list))}
                is_comp_checked = comp_ids.issubset(st.session_state['selected_ids'])
                st.checkbox("all", key=f"c_{company}", value=is_comp_checked, on_change=toggle_company_check, args=(company,), label_visibility="collapsed")
            
            with c_head2:
                st.markdown(f"### 🏭 {company} <span style='font-size:16px; color:#95a5a6; font-weight:normal;'>({len(news_list)}건)</span>", unsafe_allow_html=True)
            
            st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)

            cols = st.columns(3)
            for i, news in enumerate(news_list):
                unique_key = f"{company}_{i}"
                with cols[i % 3]:
                    with st.container(border=True):
                        # [수정] 화면에서도 📅 대신 🕒 사용
                        st.markdown(f"""
                            <a href="{news['link']}" target="_blank" class="news-link">{news['title']}</a>
                            <span class="news-date">🕒 {news['date']}</span>
                        """, unsafe_allow_html=True)
                        
                        is_checked = unique_key in st.session_state['selected_ids']
                        st.checkbox("선택", key=f"chk_{unique_key}", value=is_checked, on_change=toggle_item, args=(unique_key,))
            
            st.markdown("<hr>", unsafe_allow_html=True)

    # --- 전송 사이드바 ---
    with st.sidebar:
        st.divider()
        st.subheader("📤 전송 센터")
        
        current_selection = len(st.session_state['selected_ids'])
        st.info(f"현재 **{current_selection}건**의 뉴스가 선택되었습니다.")
        
        if current_selection > 0:
            st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
            if st.button("📨 슬랙으로 전송하기", type="primary", use_container_width=True):
                with st.spinner("메시지를 보내고 있습니다..."):
                    final_selected_items = []
                    for key in st.session_state['selected_ids']:
                        comp, idx_str = key.split('_')
                        idx = int(idx_str)
                        if comp in results and idx < len(results[comp]):
                            final_selected_items.append((comp, results[comp][idx]))

                    grouped = defaultdict(list)
                    for comp, item in final_selected_items:
                        grouped[comp].append(item)
                    
                    for comp, items in grouped.items():
                        send_company_batch(comp, items)
                        time.sleep(0.1)
                        
                    st.toast(f"✅ 총 {len(grouped)}개 기업의 뉴스를 전송했습니다!", icon="📨")
                    st.session_state['selected_ids'] = set()
                    time.sleep(1)
                    st.rerun()