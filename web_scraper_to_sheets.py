import os

# ─────── 💡 디버깅 유틸리티 추가 ───────
def save_debug_info(driver, name="debug"):
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = f"{name}_screenshot_{timestamp}.png"
    html_path = f"{name}_page_{timestamp}.html"
    try:
        driver.save_screenshot(screenshot_path)
        print(f"📸 스크린샷 저장됨: {screenshot_path}")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"📄 HTML 저장됨: {html_path}")
    except Exception as e:
        print(f"⚠️ 디버깅 정보 저장 실패: {e}")

# ─────── 인증 키 파일 저장 ───────
if os.getenv("GOOGLE_CREDENTIALS"):
    with open("service_account_credentials.json", "w") as f:
        f.write(os.getenv("GOOGLE_CREDENTIALS"))

import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ──────────────── 설정 ──────────────── #
SERVICE_ACCOUNT_FILE = 'service_account_credentials.json'
SPREADSHEET_ID = '1L_sPHkWw6nzVWCFUXnTVUuCNyJjogmyM90iFCIvluD8'
SHEET_NAME = 'FDA_WL'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
FILTER_KEYWORD = 'Finished Pharmaceuticals'
INITIAL_LOOK_BACK_YEARS = 3
MAX_PAGES = 50
# ───────────────────────────────────── #

# --- Google Sheets API 인증 ---
try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheet_service = build('sheets', 'v4', credentials=credentials)
    sheet = sheet_service.spreadsheets()
    print("✅ 구글 시트 인증 성공")
except Exception as e:
    print(f"❌ 구글 시트 인증 실패: {e}")
    exit()

# --- 날짜 파싱 함수 ---
def parse_date(date_str):
    for fmt in ('%B %d, %Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None

# --- Selenium 드라이버 설정 ---
options = webdriver.ChromeOptions()
options.add_argument('--headless')
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)
options.add_argument("start-maximized")
driver = webdriver.Chrome(service=Service(), options=options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
print("🖥️ 웹 드라이버 실행 시작")

try:
    # ✅ 크롤링 시작
    print("\n==================== 1부: 신규 목록 수집 시작 ====================")
    print("📊 구글 시트에서 마지막 날짜를 가져오는 중...")
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!A2:A2').execute()
    values = result.get('values', [])
    if values and values[0]:
        most_recent_saved_date = parse_date(values[0][0])
        start_date = most_recent_saved_date - timedelta(days=2)
        print(f"🔄 마지막 저장 날짜({most_recent_saved_date.strftime('%Y-%m-%d')}) 이후의 새로운 데이터를 확인합니다.")
    else:
        start_date = datetime.now() - timedelta(days=365 * INITIAL_LOOK_BACK_YEARS)
        print(f"🚀 첫 실행입니다. 약 {INITIAL_LOOK_BACK_YEARS}년 전의 데이터부터 수집을 시작합니다.")
    date_str_set = set((start_date + timedelta(days=i)).strftime('%m/%d/%Y') for i in range((datetime.now() - start_date).days + 1))
    print(f"📅 데이터 검색 범위: {start_date.strftime('%Y-%m-%d')} 부터 오늘까지")

    # ✅ FDA 페이지 접속
    base_url = 'https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters'
    try:
        driver.get(base_url)
        wait = WebDriverWait(driver, 20)
        search_input = wait.until(EC.visibility_of_element_located((By.ID, 'edit-search-api-fulltext')))
        search_input.send_keys(FILTER_KEYWORD)
    except Exception as e:
        print(f"❌ 페이지 초기 로딩 실패: {e}")
        save_debug_info(driver, "initial_load")
        raise

    time.sleep(4)
    try:
        info_element = wait.until(EC.visibility_of_element_located((By.ID, 'datatable_info')))
        print(f"📊 검색 정보: {info_element.text}")
    except Exception as e:
        print(f"❌ 검색 정보 확인 실패: {e}")
        save_debug_info(driver, "datatable_info")
        raise

    # 이후 기존 로직 계속...

except Exception as e:
    print(f"❌ 알 수 없는 오류 발생: {e}")
    save_debug_info(driver, "general_error")
finally:
    if 'driver' in locals():
        driver.quit()
    print("🏁 모든 작업 완료!")
