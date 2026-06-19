import streamlit as st
import feedparser
import google.generativeai as genai
import os
import urllib.parse
from bs4 import BeautifulSoup
import email.utils
from datetime import datetime, timezone, timedelta
import time
import re

# --- 1. 페이지 기본 설정 ---
st.set_page_config(page_title="GPA 뉴스 센싱 대시보드", page_icon="📰", layout="wide")
st.title("📰 글로벌 대외협력(GPA) 뉴스 센싱 대시보드")
st.markdown("주요 글로벌 매체의 48시간 내 동향을 실시간으로 수집합니다.")

# --- 2. 사이드바 (키워드 및 언론사 관리 UI) ---
with st.sidebar:
    st.header("⚙️ 대시보드 설정")
    st.markdown("쉼표(,)로 구분해 자유롭게 입력하세요.")

    # 🚨 1번 문제 해결: Streamlit 'key' 속성을 이용해 값 영구 고정
    if "kw_input" not in st.session_state:
        st.session_state.kw_input = "Trump AI, AI Chips, Anthropic, OpenAI, Bondi, David Sacks, AI Order, Glasswing, OpenAI TAC, Trusted Access for Cyber"
    if "domain_input" not in st.session_state:
        st.session_state.domain_input = "wsj.com, ft.com, bloomberg.com, reuters.com, politico.com, washingtonpost.com"

    # key를 지정해두면 새로고침을 해도 절대 날아가지 않습니다.
    st.text_area("🔍 검색 키워드 목록", key="kw_input", height=150)
    st.text_area("🌐 탐색할 언론사 사이트 (도메인)", key="domain_input", height=100)

    if st.button("💾 적용 및 새로고침", use_container_width=True):
        st.cache_data.clear() 
        st.rerun()

# 세션에 저장된 값을 바로 불러와서 사용
KEYWORDS = [kw.strip() for kw in st.session_state.kw_input.split(",") if kw.strip()]
TARGET_DOMAINS = [domain.strip() for domain in st.session_state.domain_input.split(",") if domain.strip()]

# --- 3. AI 설정 (안정적인 모델 탐색) ---
api_key = os.environ.get("GEMINI_API_KEY")
model = None

if api_key:
    genai.configure(api_key=api_key)
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]

        if available_models:
            target_model = next((m for m in available_models if '1.5-flash-8b' in m), None)
            if not target_model:
                target_model = next((m for m in available_models if '1.5-flash' in m), None)
            if not target_model:
                target_model = next((m for m in available_models if 'flash' in m and '2.' not in m), None)
            if not target_model:
                target_model = next((m for m in available_models if 'pro' in m and '2.' not in m), available_models[0])

            model = genai.GenerativeModel(target_model)
        else:
            st.sidebar.error("사용 가능한 AI 모델을 찾을 수 없습니다.")
    except Exception as e:
        st.sidebar.error(f"모델 탐색 에러: {e}")
else:
    st.error("⚠️ 좌측 [Secrets] 메뉴에서 `GEMINI_API_KEY`를 먼저 설정해주세요!")

# --- 4. 뉴스 수집 엔진 ---
@st.cache_data(ttl=1800)
def fetch_news(current_keywords, current_domains):
    if not current_keywords or not current_domains:
        return []

    query_parts = [f'"{kw}"' for kw in current_keywords]
    kw_query = " OR ".join(query_parts)
    valid_entries = []

    for domain in current_domains:
        full_query = f"({kw_query}) site:{domain} when:48h"
        encoded_query = urllib.parse.quote(full_query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(rss_url)

        for entry in feed.entries:
            title = entry.title if hasattr(entry, 'title') else ""
            desc = entry.description if hasattr(entry, 'description') else ""

            text_to_search = (title + " " + desc).lower()
            matched_tags = []

            for kw in current_keywords:
                words = kw.lower().split()
                is_all_words_matched = all(re.search(rf'\b{re.escape(word)}\b', text_to_search) for word in words)

                if is_all_words_matched:
                    matched_tags.append(f"#{kw.replace(' ', '_')}")

            if not matched_tags:
                continue

            if not any(e.link == entry.link for e in valid_entries):
                entry.matched_tags = list(set(matched_tags)) 
                valid_entries.append(entry)

    def get_timestamp(e):
        try:
            return email.utils.parsedate_to_datetime(e.published).timestamp()
        except:
            return 0.0 

    valid_entries.sort(key=get_timestamp, reverse=True)
    return valid_entries

# 🚨 2번 문제 해결: AI 에러 방어(좀비 모드) 추가
def ai_news_summarizer(title, description):
    safe_description = description[:1500] 
    
    prompt = f"""
    다음은 미국 테크/정책 뉴스의 제목과 본문 일부입니다. 
    대외협력(GPA) 부서에서 글로벌 동향 파악을 위해 참고할 수 있도록 핵심만 3줄로 한국어로 요약해 주세요.

    제목: {title}
    내용: {safe_description}
    """
    
    # 서버 에러 발생 시 최대 3번까지 알아서 재시도
    for attempt in range(3):
        try:
            response = model.generate_content(prompt)
            if response.text:
                return response.text
        except Exception:
            if attempt == 2: # 3번 다 실패했을 때만 에러 메시지 표출
                return "⚠️ 구글 AI 서버가 응답하지 않습니다. (일시적 트래픽 과부하) 잠시 후 다시 시도하거나 기사 원문을 확인해 주세요."
            time.sleep(2) # 에러 나면 2초 쉬고 다시 시도

# --- 5. 화면 출력 ---
st.subheader("📡 글로벌 매체 실시간 센싱 결과 (최근 48시간)")

if not KEYWORDS or not TARGET_DOMAINS:
    st.warning("👈 좌측 사이드바에서 검색할 키워드와 언론사 도메인을 최소 1개 이상 입력해 주세요.")
else:
    entries = fetch_news(KEYWORDS, TARGET_DOMAINS)

    if not entries:
        st.info("지정된 키워드로 최근 48시간 내에 검색된 뉴스가 없습니다.")
    else:
        st.success(f"⭐ 지정한 매체에서 조건에 완벽히 일치하는 {len(entries)}개의 뉴스를 발견했습니다.")

        for entry in entries: 
            title = entry.title
            link = entry.link
            published = entry.published
            source = entry.source.title if hasattr(entry, 'source') else "Unknown"
            description = entry.description if hasattr(entry, 'description') else ""

            try:
                dt = email.utils.parsedate_to_datetime(published)
                kst_tz = timezone(timedelta(hours=9))
                dt_kst = dt.astimezone(kst_tz)
                formatted_date = dt_kst.strftime("%m월 %d일 %H:%M (KST)")
            except:
                formatted_date = published 

            source_display = f"⭐ **{source}**"
            hashtag_display = " ".join(entry.matched_tags)

            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"#### {source_display} | {title}")
                st.markdown(f"<p style='color: #deff9a; font-weight: bold; margin-top: -10px; margin-bottom: 15px;'>{hashtag_display}</p>", unsafe_allow_html=True)
            with col2:
                st.markdown(f"<p style='text-align: right; color: gray; font-size: 14px; margin-top: 5px;'>{formatted_date}</p>", unsafe_allow_html=True)

            if link not in st.session_state:
                st.session_state[link] = ""

            if api_key and model:
                if not st.session_state[link]:
                    if st.button("🤖 AI 3줄 요약 보기", key=f"btn_{link}"):
                        soup = BeautifulSoup(description, "html.parser")
                        clean_text = soup.get_text()
                        with st.spinner("요약 중입니다... (1~2초)"):
                            summary = ai_news_summarizer(title, clean_text)
                            st.session_state[link] = summary 
                            st.rerun() 

            if st.session_state[link]:
                st.markdown(f"<div style='background-color: #262730; padding: 15px; border-radius: 10px; border-left: 5px solid #deff9a; margin-bottom: 10px;'>{st.session_state[link]}</div>", unsafe_allow_html=True)

            st.markdown(f"🔗 [기사 원문 보러가기]({link})")
            st.divider()

# --- 6. 수동 새로고침 ---
if st.button("🔄 최신 뉴스 다시 불러오기"):
    fetch_news.clear() 
    st.rerun()
