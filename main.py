import streamlit as st
import requests
import html
import pandas as pd
import re
import time
from datetime import datetime
from collections import defaultdict

# --- 1. 페이지 설정 ---
st.set_page_config(
    page_title="대성에너지 뉴스 클리핑",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CSS 스타일링 ---
st.markdown("""
    <style>
        .block-container { padding-top: 2rem; padding-bottom: 5rem; max-width: 1200px; }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 12px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.05);
            background-color: white;
        }
        .news-link {
            font-size: 16px; font-weight: 600; color: #2c3e50 !important;
            text-decoration: none; line-height: 1.5; display: block; margin-bottom: 8px;
        }
        .news-link:hover { color: #0068c3 !important; text-decoration: underline; }
        .news-date { font-size: 12px; color: #7f8c8d; margin-bottom: 12px; display: block; }
        div[data-testid="stCheckbox"] { margin-top: 5px; margin-bottom: 5px; }
        hr { margin-top: 1rem; margin-bottom: 2rem; border-color: #eee; }
        
        /* 결과 없음 메시지 스타일 */
        .no-result {
            text-align: center; color: #7f8c8d; padding: 20px;
            background-color: #f8f9fa; border-radius: 10px; margin-top: 10px;
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
if 'global_select_state' not in st.session_state:
    st.session_state['global_select_state'] = False

# --- 4. 유틸리티 함수 ---
def format_slack_date(date_str):
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

    if st.session_state.global_check:
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

# --- 7. 메인 화면 ---

st.title("📰 대량 수요처 뉴스 모니터링")
st.markdown("<div style='margin-bottom: 30px;'></div>", unsafe_allow_html=True)

full_customer_list = load_top_customers_data()
total_customers = len(full_customer_list)

# ==========================================
# [사이드바 구성]
# ==========================================
with st.sidebar:
    # 1. 검색 옵션
    st.header("🛠️ 검색 옵션")
    st.markdown("---")
    
    top_n = st.slider("📊 검색 대상 기업 수", 1, total_customers, total_customers)
    api_filter_word = st.text_input("🏷️ 수집 키워드 (API)", placeholder="예: 화재, 수주 (빈칸이면 전체)")
    
    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    
    if st.button("🔎 뉴스 분석 시작", type="primary", use_container_width=True):
        st.session_state['news_results'] = {}
        st.session_state['selected_ids'] = set()
        st.session_state['global_select_state'] = False
        
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
                filter_keywords = [k.strip() for k in api_filter_word.split(',')] if api_filter_word else []
                
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

    # 2. 전송 센터 (상시 노출)
    st.divider()
    st.subheader("📤 전송 센터")
    
    current_selection = len(st.session_state['selected_ids'])
    st.info(f"현재 **{current_selection}건** 선택됨")
    
    # 선택된 건수가 없으면 버튼 비활성화 (disabled=True)
    if st.button("📨 슬랙으로 전송하기", type="primary", use_container_width=True, disabled=(current_selection == 0)):
        with st.spinner("메시지를 보내고 있습니다..."):
            final_selected_items = []
            for key in st.session_state['selected_ids']:
                comp, idx_str = key.split('_')
                idx = int(idx_str)
                if comp in st.session_state['news_results'] and idx < len(st.session_state['news_results'][comp]):
                    final_selected_items.append((comp, st.session_state['news_results'][comp][idx]))

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

    # 3. 슬랙 채널 바로가기 (상시 노출)
    st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
    # [수정됨] 사용자가 요청한 직관적인 멘트로 변경
    st.link_button("📢 마케팅팀 슬랙 #뉴스 채널로 이동하기", "https://w1720603775-rgf723937.slack.com/archives/C0A22RMU3UH", use_container_width=True)


# ==========================================
# [메인 콘텐츠 영역]
# ==========================================
# 결과 내 재검색 기능
st.divider()
st.subheader("🔍 결과 내 필터링")
local_filter = st.text_input("결과 안에서 찾기", placeholder="예: 사망, 계약")

original_results = st.session_state['news_results']

# 1. 로컬 필터링
display_results = {}
if original_results:
    if local_filter:
        keywords = [k.strip() for k in local_filter.split(',')]
        for company, items in original_results.items():
            filtered_items = []
            for item in items:
                if any(k in item['title'] or k in item['desc'] for k in keywords):
                    filtered_items.append(item)
            if filtered_items:
                display_results[company] = filtered_items
    else:
        display_results = original_results

# 2. 결과 출력
if not original_results:
    st.info("👈 왼쪽 사이드바에서 **[뉴스 분석 시작]** 버튼을 눌러주세요.")

elif not display_results:
    st.warning(f"😥 '{local_filter}'에 해당하는 검색 결과가 없습니다.")

else:
    # 컨트롤 패널 (전체 선택 등)
    with st.container(border=True):
        c1, c2, c3 = st.columns([0.2, 0.6, 0.2])
        
        with c1:
            total_all_ids = sum(len(v) for v in st.session_state['news_results'].values())
            is_all_selected = (len(st.session_state['selected_ids']) >= total_all_ids) and (total_all_ids > 0)
            st.checkbox("✅ 전체 선택", key="global_check", value=is_all_selected, on_change=toggle_global_check)
            
        with c2:
            st.markdown(f"<div style='text-align: center; font-size: 1.1em; font-weight: bold;'>🔎 {len(display_results)}개 기업 뉴스 (필터 적용됨)</div>", unsafe_allow_html=True)
            
        with c3:
            count = len(st.session_state['selected_ids'])
            st.markdown(f"<div style='text-align: right; color: #e74c3c; font-weight: bold;'>선택됨: {count}건</div>", unsafe_allow_html=True)

    st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

    # 뉴스 리스트 출력
    for company, news_list in display_results.items():
        with st.container():
            c_head1, c_head2 = st.columns([0.05, 0.95])
            with c_head1:
                comp_ids = {f"{company}_{i}" for i in range(len(st.session_state['news_results'][company]))}
                is_comp_checked = comp_ids.issubset(st.session_state['selected_ids'])
                st.checkbox("all", key=f"c_{company}", value=is_comp_checked, on_change=toggle_company_check, args=(company,), label_visibility="collapsed")
            
            with c_head2:
                st.markdown(f"### 🏭 {company} <span style='font-size:16px; color:#95a5a6; font-weight:normal;'>({len(news_list)}건)</span>", unsafe_allow_html=True)
            
            st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)

            cols = st.columns(3)
            for i, news in enumerate(news_list):
                original_idx = -1
                original_items = st.session_state['news_results'][company]
                for o_idx, o_item in enumerate(original_items):
                    if o_item['link'] == news['link']:
                        original_idx = o_idx
                        break
                
                if original_idx != -1:
                    unique_key = f"{company}_{original_idx}"
                    
                    with cols[i % 3]:
                        with st.container(border=True):
                            st.markdown(f"""
                                <a href="{news['link']}" target="_blank" class="news-link">{news['title']}</a>
                                <span class="news-date">🕒 {news['date']}</span>
                            """, unsafe_allow_html=True)
                            
                            is_checked = unique_key in st.session_state['selected_ids']
                            st.checkbox("선택", key=f"chk_{unique_key}", value=is_checked, on_change=toggle_item, args=(unique_key,))
            
            st.markdown("<hr>", unsafe_allow_html=True)