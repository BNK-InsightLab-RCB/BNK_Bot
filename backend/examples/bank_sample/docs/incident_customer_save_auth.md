# 고객조회 저장 권한 오류 이력

- Screen: 고객조회
- Action: 저장
- Error: 저장 권한이 없습니다.
- Cause: 일부 영업점 직원에게 CUSTOMER_SAVE 권한이 부여되지 않아 저장 API에서 업무 예외가 발생했다.
- Branch Guide: 지점 권한 담당자 또는 IT부서에 고객정보 저장 권한 보유 여부를 확인한다.
- IT Guide: CustomerService.saveCustomer 권한 체크와 사용자 권한 매핑을 확인한다.
