# PostgreSQL 설정 가이드

**작성일:** 2025-12-17  
**목적:** SQLite 대신 PostgreSQL 사용하기

---

## 🤔 왜 PostgreSQL?

### SQLite 한계
- ❌ **단일 PK만 허용** (복합 키 불가)
- ❌ **ALTER TABLE 제한** (FK 추가 불가)
- ❌ **동시 쓰기 제한** (단일 사용자용)
- ❌ **제한적 데이터 타입**

### PostgreSQL 장점
- ✅ **복합 PK 지원**
  ```sql
  PRIMARY KEY (caseid, dt, name)  -- 가능!
  ```
- ✅ **완전한 FK 지원** (CASCADE, ON DELETE 등)
- ✅ **동시 접속** (멀티 유저)
- ✅ **프로덕션 준비**

---

## 🚀 빠른 설정 (자동)

### 자동 설정 스크립트 실행

```bash
cd /Users/goeastagent/products/MedicalAIMaster/IndexingAgent
./setup_postgres.sh
```

**자동으로 수행:**
1. ✅ PostgreSQL 설치 (Homebrew)
2. ✅ 서비스 시작
3. ✅ `medical_data` 데이터베이스 생성
4. ✅ `.env` 파일 설정
5. ✅ `psycopg2-binary` 설치
6. ✅ 연결 테스트

**소요 시간:** ~5분

---

## 🔧 수동 설정 (상세)

### 1. PostgreSQL 설치

#### macOS (Homebrew)
```bash
brew install postgresql@15
brew services start postgresql@15
```

#### Ubuntu/Debian
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql
```

---

### 2. 데이터베이스 생성

```bash
# PostgreSQL 접속
psql -U postgres

# 데이터베이스 생성
CREATE DATABASE medical_data;

# 확인
\l

# 종료
\q
```

---

### 3. .env 파일 설정

```bash
# .env 파일에 추가
cat >> .env << EOF

# PostgreSQL 설정
DB_TYPE=postgresql
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=medical_data
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-password-here
EOF
```

---

### 4. Python 패키지 설치

```bash
pip install psycopg2-binary
```

---

### 5. 연결 테스트

```python
python << PYTHON
import sys
sys.path.insert(0, 'src')

from database.connection import DatabaseManager

db = DatabaseManager(db_type="postgresql")
conn = db.connect()
print("✅ 연결 성공!")
conn.close()
PYTHON
```

---

## 📊 SQLite vs PostgreSQL 사용법

### SQLite (기본값)

**.env 파일:**
```bash
DB_TYPE=sqlite
# 또는 설정 안 함 (기본값)
```

**실행:**
```bash
python test_agent_with_interrupt.py
# → data/processed/medical_data.db 생성
```

---

### PostgreSQL

**.env 파일:**
```bash
DB_TYPE=postgresql
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=medical_data
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your-password
```

**실행:**
```bash
python test_agent_with_interrupt.py
# → PostgreSQL의 medical_data DB에 테이블 생성
```

---

## 🔍 PostgreSQL DB 확인

### psql로 확인
```bash
# PostgreSQL 접속
psql -U postgres -d medical_data

# 테이블 목록
\dt

# 테이블 구조 확인
\d clinical_data_table

# 행 개수 확인
SELECT COUNT(*) FROM clinical_data_table;

# FK 확인
\d+ lab_data_table

# 종료
\q
```

---

### view_database.py로 확인

```bash
# SQLite 확인
python view_database.py

# PostgreSQL 확인 (향후 지원 예정)
python view_database.py --db postgresql
```

---

## 💡 권장 사항

### 개발 단계
- ✅ **SQLite 사용** (간단, 빠름)
- 복합 PK 필요 없으면 충분

### 프로덕션 단계
- ✅ **PostgreSQL 사용** (안정적, 확장성)
- 복합 PK, FK Cascade 필요
- 멀티 유저 접속

---

## 🐛 트러블슈팅

### "PostgreSQL 시작 안 됨"
```bash
# macOS
brew services restart postgresql@15

# Linux
sudo systemctl restart postgresql
```

### "비밀번호 인증 실패"
```bash
# PostgreSQL 설정 확인
sudo cat /opt/homebrew/var/postgresql@15/pg_hba.conf

# trust로 변경 (로컬 개발용)
# local   all   all   trust
```

### "데이터베이스 접속 안 됨"
```bash
# 연결 확인
psql -U postgres -h localhost -p 5432

# .env 파일 확인
cat .env | grep POSTGRES
```

---

## 🔄 SQLite ↔ PostgreSQL 전환

### SQLite → PostgreSQL

```bash
# 1. PostgreSQL 설정
./setup_postgres.sh

# 2. .env 수정
DB_TYPE=postgresql

# 3. 재실행
python test_agent_with_interrupt.py
# → PostgreSQL에 테이블 생성
```

---

### PostgreSQL → SQLite

```bash
# .env 수정
DB_TYPE=sqlite
# 또는 DB_TYPE 주석 처리

# 재실행
python test_agent_with_interrupt.py
# → SQLite로 돌아감
```

---

## 📋 체크리스트

설치 및 설정:
- [ ] PostgreSQL 설치됨
- [ ] 서비스 실행 중
- [ ] `medical_data` DB 생성됨
- [ ] `.env` 파일 설정됨
- [ ] `psycopg2-binary` 설치됨
- [ ] 연결 테스트 성공

실행:
- [ ] `test_agent_with_interrupt.py` 실행
- [ ] 테이블 생성 확인
- [ ] 데이터 적재 확인
- [ ] FK 제약조건 확인

---

**상태:** PostgreSQL 지원 완료 ✅  
**설정:** `./setup_postgres.sh` 실행으로 자동화

