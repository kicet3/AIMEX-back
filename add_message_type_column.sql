-- CHAT_MESSAGE 테이블에 message_type 컬럼 추가

-- 기존 데이터 백업
CREATE TABLE CHAT_MESSAGE_BACKUP AS SELECT * FROM CHAT_MESSAGE;

-- message_type 컬럼 추가
ALTER TABLE CHAT_MESSAGE 
ADD COLUMN message_type VARCHAR(20) NOT NULL DEFAULT 'user' COMMENT '메시지 타입 (user/ai)';

-- 기존 데이터 업데이트 (USER: 또는 AI: 접두사 기반으로 타입 설정)
UPDATE CHAT_MESSAGE 
SET message_type = 'user' 
WHERE message_content LIKE 'USER:%';

UPDATE CHAT_MESSAGE 
SET message_type = 'ai' 
WHERE message_content LIKE 'AI:%';

-- 접두사 제거 (message_type 컬럼이 있으므로 불필요)
UPDATE CHAT_MESSAGE 
SET message_content = SUBSTRING(message_content, 6) 
WHERE message_content LIKE 'USER:%';

UPDATE CHAT_MESSAGE 
SET message_content = SUBSTRING(message_content, 4) 
WHERE message_content LIKE 'AI:%';

-- 변경 확인
DESCRIBE CHAT_MESSAGE;

-- 백업 테이블 삭제 (확인 후)
-- DROP TABLE CHAT_MESSAGE_BACKUP; 