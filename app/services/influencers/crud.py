from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.models.influencer import AIInfluencer, ModelMBTI, StylePreset, InfluencerAPI
from app.schemas.influencer import AIInfluencerCreate, AIInfluencerUpdate
from app.utils.data_mapping import DataMapper
from fastapi import HTTPException, status
import uuid
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


async def get_influencer_by_id(db: Session, user_id: str, influencer_id: str):
    """인플루언서 조회 (권한 체크 포함)"""
    from app.models.user import User

    # 사용자 정보 조회 (팀 정보 포함)
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # 사용자가 속한 그룹 ID 목록
    user_group_ids = [team.group_id for team in user.teams] if user.teams else []

    # 인플루언서 조회 (권한 체크 포함)
    query = db.query(AIInfluencer).filter(AIInfluencer.influencer_id == influencer_id)

    # 권한 체크: 사용자가 속한 그룹의 인플루언서이거나 사용자가 직접 소유한 인플루언서
    if user_group_ids:
        query = query.filter(
            (AIInfluencer.group_id.in_(user_group_ids))
            | (AIInfluencer.user_id == user_id)
        )
    else:
        # 그룹이 없는 경우 사용자가 직접 소유한 인플루언서만
        query = query.filter(AIInfluencer.user_id == user_id)

    influencer = query.first()
    if not influencer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Influencer not found or access denied",
        )

    return influencer


async def get_influencers_list(db: Session, user_id: str, skip: int = 0, limit: int = 100):
    """인플루언서 목록 조회 (권한 체크 포함)"""
    from app.models.user import User

    # 사용자 정보 조회 (팀 정보 포함)
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    # 사용자가 속한 그룹 ID 목록
    user_group_ids = [team.group_id for team in user.teams] if user.teams else []

    # 인플루언서 조회 (권한 체크 포함)
    query = db.query(AIInfluencer)

    # 권한 체크: 사용자가 속한 그룹의 인플루언서이거나 사용자가 직접 소유한 인플루언서
    if user_group_ids:
        query = query.filter(
            (AIInfluencer.group_id.in_(user_group_ids))
            | (AIInfluencer.user_id == user_id)
        )
    else:
        # 그룹이 없는 경우 사용자가 직접 소유한 인플루언서만
        query = query.filter(AIInfluencer.user_id == user_id)

    # 정렬 및 페이징
    influencers = query.order_by(AIInfluencer.created_at.desc()).offset(skip).limit(limit).all()
    
    return influencers


async def create_influencer(db: Session, user_id: str, influencer_data: AIInfluencerCreate):
    """새 AI 인플루언서 생성"""
    logger.info(
        f"🎨 인플루언서 생성 시작 - user_id: {user_id}, name: {influencer_data.influencer_name}"
    )

    from app.services.influencers.style_presets import create_style_preset
    from app.schemas.influencer import StylePresetCreate

    style_preset_id = influencer_data.style_preset_id
    if not style_preset_id:
        if influencer_data.personality and influencer_data.tone:
            age_group = DataMapper.map_age_to_group(influencer_data.age)

            preset_data = StylePresetCreate(
                style_preset_name=f"{influencer_data.influencer_name}_자동생성프리셋",
                influencer_type=DataMapper.map_model_type_to_db(
                    influencer_data.model_type
                ),
                influencer_gender=DataMapper.map_gender_to_db(influencer_data.gender),
                influencer_age_group=age_group,
                influencer_hairstyle=influencer_data.hair_style or "이미지로 업로드 됨.",
                influencer_style=influencer_data.mood or "이미지로 업로드 됨.",
                influencer_personality=influencer_data.personality,
                influencer_speech=influencer_data.tone,
                influencer_description=influencer_data.influencer_description or f"{influencer_data.influencer_name}의 AI 인플루언서",
                system_prompt=influencer_data.system_prompt,  # 시스템 프롬프트 추가
            )
            print(preset_data)
            style_preset = create_style_preset(db, preset_data)
            style_preset_id = style_preset.style_preset_id
        else:
            style_preset_id = None  # 명시적으로 None으로 설정
    else:
        style_preset = (
            db.query(StylePreset)
            .filter(StylePreset.style_preset_id == style_preset_id)
            .first()
        )
        if not style_preset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Style preset not found"
            )

    # MBTI 처리: 텍스트로 받은 경우 mbti_id로 변환
    mbti_id = influencer_data.mbti_id
    mbti_name = None  # MBTI 타입 이름 (예: ENFP)
    
    # MBTI 텍스트가 있고 mbti_id가 없는 경우
    if influencer_data.mbti and not mbti_id:
        mbti_text = influencer_data.mbti.upper()  # 대문자로 변환
        mbti_record = (
            db.query(ModelMBTI)
            .filter(ModelMBTI.mbti_name == mbti_text)
            .first()
        )
        if mbti_record:
            mbti_id = mbti_record.mbti_id
            mbti_name = mbti_record.mbti_name
            logger.info(f"✅ MBTI 텍스트 '{mbti_text}'를 mbti_id {mbti_id}로 변환")
        else:
            logger.warning(f"⚠️ 유효하지 않은 MBTI 타입: {mbti_text}")
            # 잘못된 MBTI 타입인 경우 에러 발생
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"유효하지 않은 MBTI 타입입니다: {mbti_text}"
            )

    # mbti_id가 설정된 경우 유효성 검증 및 mbti_name 가져오기
    if mbti_id:
        mbti = db.query(ModelMBTI).filter(ModelMBTI.mbti_id == mbti_id).first()
        if not mbti:
            logger.warning(f"⚠️ 존재하지 않는 mbti_id: {mbti_id}")
            mbti_id = None
        else:
            mbti_name = mbti.mbti_name
            logger.info(f"✅ mbti_id {mbti_id}에서 MBTI 타입 '{mbti_name}' 조회")

    hf_manage_id = influencer_data.hf_manage_id
    if hf_manage_id in ["", "none", None]:
        hf_manage_id = None
    else:
        # 허깅페이스 토큰 존재 확인
        from app.models.user import HFTokenManage

        hf_token = (
            db.query(HFTokenManage)
            .filter(HFTokenManage.hf_manage_id == hf_manage_id)
            .first()
        )
        if not hf_token:
            logger.warning(f"⚠️ 지정된 허깅페이스 토큰을 찾을 수 없음: {hf_manage_id}")
            hf_manage_id = None

    # 시스템 프롬프트 처리
    final_system_prompt = influencer_data.system_prompt
    
    # 프리셋이 있고 시스템 프롬프트가 없다면 프리셋에서 가져오기
    if not final_system_prompt and style_preset_id:
        style_preset = (
            db.query(StylePreset)
            .filter(StylePreset.style_preset_id == style_preset_id)
            .first()
        )
        if style_preset and style_preset.system_prompt:
            final_system_prompt = style_preset.system_prompt
            logger.info(f"📝 프리셋에서 시스템 프롬프트 가져옴: {style_preset_id}")
    
    # 말투 정보 처리 - tone_data가 있고 system_prompt가 없으면 분석
    if influencer_data.tone_type and influencer_data.tone_data:
        logger.info(f"📝 말투 정보 처리: type={influencer_data.tone_type}")
        
        # system_prompt가 없으면 tone_data를 분석하여 생성
        if not influencer_data.system_prompt and not final_system_prompt:
            logger.info("🔍 tone_data 분석을 통한 시스템 프롬프트 생성 시작")
            try:
                
                
                # 캐릭터 정보 구성
                character_info = {
                    "name": influencer_data.influencer_name,
                    "description": influencer_data.influencer_description or "",
                    "age": influencer_data.age,
                    "personality": influencer_data.personality,
                    "mbti": influencer_data.mbti or "MBTI 정보 없음",
                    "gender": influencer_data.gender or "성별 정보 없음"
                }
                
                # tone_data 분석
                async with RunPodClient() as runpod_client:
                    analysis_result = await runpod_client.analyze_tone_data(
                        tone_data=influencer_data.tone_data,
                        character_info=character_info
                    )
                
                # 분석된 시스템 프롬프트 사용
                final_system_prompt = analysis_result.get("system_prompt", "")
                logger.info(f"✅ 시스템 프롬프트 생성 완료: {final_system_prompt[:100]}...")
                
                # 분석 결과도 별도로 저장할 수 있음 (필요시)
                # influencer_create_data["tone_analysis"] = analysis_result.get("tone_analysis", "")
                
            except Exception as e:
                logger.error(f"❌ tone_data 분석 실패: {e}")
                # 분석 실패시 기본 프롬프트 사용
                final_system_prompt = f"당신은 {influencer_data.influencer_name}입니다. 주어진 대사 스타일로 대화해주세요."
        else:
            # 이미 system_prompt가 있으면 그대로 사용
            final_system_prompt = influencer_data.system_prompt or final_system_prompt
    
    print(f"final_system_prompt: {final_system_prompt}")
    # 인플루언서 생성 데이터 준비
    influencer_create_data = {
        "influencer_id": str(uuid.uuid4()),
        "user_id": user_id,
        "group_id": influencer_data.group_id,
        "style_preset_id": style_preset_id,  # 이제 None이 될 수 있음
        "mbti_id": mbti_id,
        "hf_manage_id": hf_manage_id,  # 검증된 허깅페이스 토큰 ID
        "influencer_name": influencer_data.influencer_name,
        "influencer_description": influencer_data.influencer_description,
        "image_url": influencer_data.image_url,
        "influencer_data_url": influencer_data.influencer_data_url,
        "learning_status": influencer_data.learning_status,
        "influencer_model_repo": influencer_data.influencer_model_repo,
        "chatbot_option": influencer_data.chatbot_option,
        "influencer_personality": influencer_data.personality,
        "influencer_tone": influencer_data.tone,
        "influencer_age_group": None,  # 초기화 후 아래에서 매핑
        "system_prompt": final_system_prompt,
    }

    # 스키마의 age를 모델의 influencer_age_group으로 매핑
    influencer_create_data["influencer_age_group"] = DataMapper.map_age_to_group(
        influencer_data.age
    )

    try:
        # 인플루언서 생성
        influencer = AIInfluencer(**influencer_create_data)
        print(f"influencer: {influencer}")
        db.add(influencer)
        db.flush()  # ID 생성을 위해 flush

        # API 키 자동 생성
        api_key = f"ai_inf_{uuid.uuid4().hex[:16]}"
        influencer_api = InfluencerAPI(
            influencer_id=influencer.influencer_id, api_value=api_key
        )
        db.add(influencer_api)

        db.commit()
        db.refresh(influencer)

        logger.info(
            f"🎉 인플루언서 생성 완료 - ID: {influencer.influencer_id}, 이름: {influencer.influencer_name}"
        )
        logger.info(f"🔑 API 키 자동 생성 완료 - 키: {api_key}")

    except IntegrityError as e:
        db.rollback()
        if "Duplicate entry" in str(e) and "influencer_name" in str(e):
            logger.error(
                f"❌ 중복된 인플루언서 이름: {influencer_data.influencer_name}"
            )
            raise HTTPException(
                status_code=400,
                detail=f"이미 존재하는 인플루언서 이름입니다: {influencer_data.influencer_name}",
            )
        else:
            logger.error(f"❌ 인플루언서 생성 중 데이터베이스 오류: {e}")
            raise HTTPException(
                status_code=500, detail="인플루언서 생성 중 오류가 발생했습니다."
            )

    logger.info(
        f"🎉 인플루언서 생성 완료 - ID: {influencer.influencer_id}, 이름: {influencer.influencer_name}"
    )

    return influencer


async def update_influencer(
    db: Session, user_id: str, influencer_id: str, influencer_update: AIInfluencerUpdate
):
    """AI 인플루언서 정보 수정"""
    influencer = await get_influencer_by_id(db, user_id, influencer_id)

    # 업데이트할 필드들
    update_data = influencer_update.model_dump(exclude_unset=True)
    
    # chatbot_option이 활성화되는지 확인
    if 'chatbot_option' in update_data and update_data['chatbot_option'] == True:
        # 현재 chatbot_option이 False인 경우에만 LoRA 어댑터를 로드
        if not influencer.chatbot_option and influencer.influencer_model_repo:
            logger.info(f"🤖 챗봇 옵션 활성화 감지 - LoRA 어댑터 로드 시작: {influencer.influencer_name}")
            
            from app.models.user import HFTokenManage
            
            # 허깅페이스 토큰 가져오기
            hf_token = None
            if influencer.hf_manage_id:
                hf_manage = db.query(HFTokenManage).filter(
                    HFTokenManage.hf_manage_id == influencer.hf_manage_id
                ).first()
                if hf_manage:
                    hf_token = hf_manage.hf_token_value
            
            # LoRA 어댑터 로드 (비동기 방식)
            try:
                adapter_loaded = await runpod_load_adapter_if_needed(
                    model_id=influencer.influencer_id,
                    hf_repo_name=influencer.influencer_model_repo,
                    hf_token=hf_token
                )
                
                if adapter_loaded:
                    logger.info(f"✅ LoRA 어댑터 로드 성공: {influencer.influencer_name}")
                else:
                    logger.warning(f"⚠️ LoRA 어댑터 로드 실패: {influencer.influencer_name}")
                    
            except Exception as e:
                logger.error(f"❌ LoRA 어댑터 로드 중 오류 발생: {e}")
    
    for field, value in update_data.items():
        setattr(influencer, field, value)

    db.commit()
    db.refresh(influencer)
    return influencer


async def delete_influencer(db: Session, user_id: str, influencer_id: str):
    """AI 인플루언서 삭제"""
    influencer = await get_influencer_by_id(db, user_id, influencer_id)

    # 연관된 데이터 삭제 순서가 중요함 (외래키 제약 때문에)
    from app.models.influencer import BatchKey, InfluencerAPI, APICallAggregation

    # 1. 먼저 API 호출 집계 데이터 삭제 (InfluencerAPI를 참조하는 테이블)
    # API ID들을 먼저 조회 (리스트로 변환)
    api_ids = [row[0] for row in db.query(InfluencerAPI.api_id).filter(
        InfluencerAPI.influencer_id == influencer_id
    ).all()]
    
    if api_ids:
        # API_CALL_AGGREGATION 데이터 삭제
        db.query(APICallAggregation).filter(
            APICallAggregation.api_id.in_(api_ids)
        ).delete(synchronize_session='fetch')
        logger.info(f"🗑️ 인플루언서 {influencer_id}의 API 호출 집계 데이터 삭제 완료")

    # 2. InfluencerAPI 데이터 삭제
    db.query(InfluencerAPI).filter(
        InfluencerAPI.influencer_id == influencer_id
    ).delete(synchronize_session='fetch')
    logger.info(f"🗑️ 인플루언서 {influencer_id}의 API 키 데이터 삭제 완료")

    # 3. BatchKey 데이터 삭제
    db.query(BatchKey).filter(
        BatchKey.influencer_id == influencer_id
    ).delete(synchronize_session='fetch')
    logger.info(f"🗑️ 인플루언서 {influencer_id}와 연관된 BatchKey 데이터 삭제 완료")

    # 4. 마지막으로 인플루언서 삭제
    db.delete(influencer)
    db.commit()

    logger.info(f"✅ 인플루언서 {influencer_id} 삭제 완료")
    return {"message": "Influencer deleted successfully"}
