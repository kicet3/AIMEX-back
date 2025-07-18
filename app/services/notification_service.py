"""
알림 서비스
이메일 및 웹 알림 기능 제공
"""

import os
import smtplib
import logging
from datetime import datetime
from typing import Optional, Dict, List
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import dataclass
from enum import Enum
import asyncio
from sqlalchemy.orm import Session
from app.utils.timezone_utils import get_current_kst

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    EMAIL = "email"
    WEB = "web"
    PUSH = "push"


class NotificationPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class NotificationTemplate:
    subject: str
    html_content: str
    text_content: str


@dataclass
class WebNotification:
    id: str
    user_id: str
    title: str
    message: str
    type: str
    read: bool = False
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = get_current_kst()


class EmailService:
    def __init__(self):
        """이메일 서비스 초기화"""
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USERNAME")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.from_email = os.getenv("FROM_EMAIL", self.smtp_username)

        self.is_configured = all(
            [self.smtp_username, self.smtp_password, self.from_email]
        )

        if not self.is_configured:
            logger.warning(
                "이메일 서비스 설정이 완전하지 않습니다. 환경변수를 확인해주세요."
            )

    def create_finetuning_completion_template(
        self, influencer_name: str, model_url: str
    ) -> NotificationTemplate:
        """파인튜닝 완료 이메일 템플릿 생성"""
        subject = f"🎉 {influencer_name} AI 모델 학습 완료!"

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .button {{ display: inline-block; background: #667eea; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }}
                .info-box {{ background: white; padding: 20px; border-left: 4px solid #667eea; margin: 20px 0; }}
                .footer {{ text-align: center; padding: 20px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎉 AI 모델 학습 완료!</h1>
                    <p>당신의 AI 인플루언서가 준비되었습니다</p>
                </div>
                <div class="content">
                    <div class="info-box">
                        <h3>📋 학습 정보</h3>
                        <p><strong>인플루언서명:</strong> {influencer_name}</p>
                        <p><strong>완료 시간:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        <p><strong>학습 데이터:</strong> 2,000개 QA 쌍</p>
                        <p><strong>모델 유형:</strong> EXAONE 3.5 2.4B (LoRA 파인튜닝)</p>
                    </div>
                    
                    <h3>🚀 이제 무엇을 할 수 있나요?</h3>
                    <ul>
                        <li>AI 인플루언서와 실시간 채팅</li>
                        <li>소셜미디어 콘텐츠 자동 생성</li>
                        <li>브랜드 맞춤형 마케팅 메시지 작성</li>
                        <li>고객과의 개인화된 상호작용</li>
                    </ul>
                    
                    <div style="text-align: center;">
                        <a href="{model_url}" class="button">🤖 모델 확인하기</a>
                        <a href="#" class="button">💬 채팅 시작하기</a>
                    </div>
                    
                    <div class="info-box">
                        <h4>💡 팁</h4>
                        <p>최상의 결과를 위해 AI 인플루언서와 대화할 때 구체적이고 명확한 질문을 해보세요!</p>
                    </div>
                </div>
                <div class="footer">
                    <p>SKN Team AI 인플루언서 플랫폼</p>
                    <p>궁금한 점이 있으시면 언제든지 문의해주세요.</p>
                </div>
            </div>
        </body>
        </html>
        """

        text_content = f"""
        🎉 AI 모델 학습 완료!
        
        안녕하세요!
        
        {influencer_name} AI 인플루언서의 모델 학습이 성공적으로 완료되었습니다.
        
        📋 학습 정보:
        - 인플루언서명: {influencer_name}
        - 완료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        - 학습 데이터: 2,000개 QA 쌍
        - 모델 유형: EXAONE 3.5 2.4B (LoRA 파인튜닝)
        
        🚀 이제 무엇을 할 수 있나요?
        - AI 인플루언서와 실시간 채팅
        - 소셜미디어 콘텐츠 자동 생성
        - 브랜드 맞춤형 마케팅 메시지 작성
        - 고객과의 개인화된 상호작용
        
        모델 확인: {model_url}
        
        💡 팁: 최상의 결과를 위해 AI 인플루언서와 대화할 때 구체적이고 명확한 질문을 해보세요!
        
        ---
        SKN Team AI 인플루언서 플랫폼
        궁금한 점이 있으시면 언제든지 문의해주세요.
        """

        return NotificationTemplate(
            subject=subject, html_content=html_content, text_content=text_content
        )

    def send_email(self, to_email: str, template: NotificationTemplate) -> bool:
        """이메일 전송"""
        if not self.is_configured:
            logger.error("이메일 서비스가 설정되지 않았습니다")
            return False

        try:
            # MIME 메시지 생성
            msg = MIMEMultipart("alternative")
            msg["Subject"] = template.subject
            msg["From"] = self.from_email
            msg["To"] = to_email

            # 텍스트 및 HTML 파트 추가
            text_part = MIMEText(template.text_content, "plain", "utf-8")
            html_part = MIMEText(template.html_content, "html", "utf-8")

            msg.attach(text_part)
            msg.attach(html_part)

            # SMTP 서버 연결 및 전송
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)

            logger.info(f"이메일 전송 성공: {to_email}")
            return True

        except Exception as e:
            logger.error(f"이메일 전송 실패: {to_email}, {e}")
            return False


class WebNotificationService:
    def __init__(self):
        """웹 알림 서비스 초기화"""
        self.notifications: Dict[str, List[WebNotification]] = {}
        self.next_id = 1

    def create_notification(
        self, user_id: str, title: str, message: str, notification_type: str = "info"
    ) -> WebNotification:
        """웹 알림 생성"""
        notification = WebNotification(
            id=str(self.next_id),
            user_id=user_id,
            title=title,
            message=message,
            type=notification_type,
        )

        if user_id not in self.notifications:
            self.notifications[user_id] = []

        self.notifications[user_id].append(notification)
        self.next_id += 1

        logger.info(f"웹 알림 생성: {user_id} - {title}")
        return notification

    def get_user_notifications(
        self, user_id: str, unread_only: bool = False
    ) -> List[WebNotification]:
        """사용자 알림 조회"""
        user_notifications = self.notifications.get(user_id, [])

        if unread_only:
            return [n for n in user_notifications if not n.read]

        return user_notifications

    def mark_as_read(self, user_id: str, notification_id: str) -> bool:
        """알림을 읽음으로 표시"""
        user_notifications = self.notifications.get(user_id, [])

        for notification in user_notifications:
            if notification.id == notification_id:
                notification.read = True
                logger.info(f"알림 읽음 처리: {user_id} - {notification_id}")
                return True

        return False

    def mark_all_as_read(self, user_id: str) -> int:
        """모든 알림을 읽음으로 표시"""
        user_notifications = self.notifications.get(user_id, [])
        count = 0

        for notification in user_notifications:
            if not notification.read:
                notification.read = True
                count += 1

        logger.info(f"모든 알림 읽음 처리: {user_id} - {count}개")
        return count

    def delete_notification(self, user_id: str, notification_id: str) -> bool:
        """알림 삭제"""
        user_notifications = self.notifications.get(user_id, [])

        for i, notification in enumerate(user_notifications):
            if notification.id == notification_id:
                del user_notifications[i]
                logger.info(f"알림 삭제: {user_id} - {notification_id}")
                return True

        return False


class NotificationService:
    def __init__(self):
        """통합 알림 서비스 초기화"""
        self.email_service = EmailService()
        self.web_service = WebNotificationService()

    async def send_finetuning_completion_notification(
        self, user_email: str, user_id: str, influencer_name: str, model_url: str
    ):
        """파인튜닝 완료 알림 전송 (이메일 + 웹)"""
        try:
            # 이메일 알림
            if self.email_service.is_configured and user_email:
                template = self.email_service.create_finetuning_completion_template(
                    influencer_name, model_url
                )

                # 비동기로 이메일 전송
                loop = asyncio.get_event_loop()
                email_success = await loop.run_in_executor(
                    None, self.email_service.send_email, user_email, template
                )

                if email_success:
                    logger.info(f"파인튜닝 완료 이메일 전송 성공: {user_email}")
                else:
                    logger.error(f"파인튜닝 완료 이메일 전송 실패: {user_email}")

            # 웹 알림
            self.web_service.create_notification(
                user_id=user_id,
                title=f"🎉 {influencer_name} AI 모델 학습 완료!",
                message=f"{influencer_name} AI 인플루언서의 모델 학습이 완료되었습니다. 이제 AI와 채팅을 시작할 수 있습니다!",
                notification_type="success",
            )

            logger.info(f"파인튜닝 완료 알림 전송 완료: {user_id}")

        except Exception as e:
            logger.error(f"파인튜닝 완료 알림 전송 실패: {e}")

    def get_web_notifications(
        self, user_id: str, unread_only: bool = False
    ) -> List[Dict]:
        """웹 알림 조회 (API 응답용)"""
        notifications = self.web_service.get_user_notifications(user_id, unread_only)

        return [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "type": n.type,
                "read": n.read,
                "created_at": n.created_at.isoformat(),
            }
            for n in notifications
        ]

    def mark_notification_read(self, user_id: str, notification_id: str) -> bool:
        """알림 읽음 처리"""
        return self.web_service.mark_as_read(user_id, notification_id)

    def mark_all_notifications_read(self, user_id: str) -> int:
        """모든 알림 읽음 처리"""
        return self.web_service.mark_all_as_read(user_id)

    def delete_notification(self, user_id: str, notification_id: str) -> bool:
        """알림 삭제"""
        return self.web_service.delete_notification(user_id, notification_id)


# 전역 알림 서비스 인스턴스
notification_service = NotificationService()


def get_notification_service() -> NotificationService:
    """알림 서비스 의존성 주입용 함수"""
    return notification_service
