-- 음성 관련 테이블 생성 SQL

-- 베이스 음성 테이블
CREATE TABLE IF NOT EXISTS voice_base (
    id INT AUTO_INCREMENT PRIMARY KEY,
    influencer_id VARCHAR(255) NOT NULL UNIQUE,
    file_name VARCHAR(255) NOT NULL,
    file_size INT,
    file_type VARCHAR(50),
    s3_url TEXT NOT NULL,
    s3_key VARCHAR(500) NOT NULL,
    duration FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    FOREIGN KEY (influencer_id) REFERENCES AI_INFLUENCER(influencer_id) ON DELETE CASCADE,
    INDEX idx_voice_base_influencer (influencer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 생성된 음성 테이블
CREATE TABLE IF NOT EXISTS generated_voice (
    id INT AUTO_INCREMENT PRIMARY KEY,
    influencer_id VARCHAR(255) NOT NULL,
    base_voice_id INT NOT NULL,
    text TEXT NOT NULL,
    s3_url TEXT NOT NULL,
    s3_key VARCHAR(500) NOT NULL,
    duration FLOAT,
    file_size INT,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (influencer_id) REFERENCES AI_INFLUENCER(influencer_id) ON DELETE CASCADE,
    FOREIGN KEY (base_voice_id) REFERENCES voice_base(id) ON DELETE CASCADE,
    INDEX idx_generated_voice_influencer (influencer_id),
    INDEX idx_generated_voice_base_voice (base_voice_id),
    INDEX idx_generated_voice_deleted (is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;