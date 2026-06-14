# TB_TRANSFER table definition

| COLUMN | TYPE | DESCRIPTION |
| --- | --- | --- |
| TRANSFER_ID | VARCHAR(30) | 이체거래번호 |
| FROM_ACCOUNT_NO | VARCHAR(20) | 출금계좌번호 |
| TO_ACCOUNT_NO | VARCHAR(20) | 입금계좌번호 |
| AMOUNT | DECIMAL(18,0) | 이체금액 |
| STATUS | VARCHAR(20) | COMPLETED 또는 FAILED |
| TRANSFER_DATE | DATE | 이체일자 |
