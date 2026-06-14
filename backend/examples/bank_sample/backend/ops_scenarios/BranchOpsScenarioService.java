package com.example.branch.ops;

import org.springframework.stereotype.Service;

@Service
public class BranchOpsScenarioService {
    private final BranchOpsScenarioMapper scenarioMapper;
    private final IdentityVerifier identityVerifier;
    private final AmlChecker amlChecker;
    private final HolidayCalendar holidayCalendar;

    public BranchOpsScenarioService(
        BranchOpsScenarioMapper scenarioMapper,
        IdentityVerifier identityVerifier,
        AmlChecker amlChecker,
        HolidayCalendar holidayCalendar
    ) {
        this.scenarioMapper = scenarioMapper;
        this.identityVerifier = identityVerifier;
        this.amlChecker = amlChecker;
        this.holidayCalendar = holidayCalendar;
    }

    public void releaseDormant(DormantReleaseRequest request, User user) {
        if (!user.hasRole("DORMANT_RELEASE")) {
            throw new BizException("E_ACCT_403", "휴면계좌 해제 권한이 없습니다.");
        }

        Account account = scenarioMapper.selectDormantAccount(request.getAccountNo());
        if (account == null || !"DORMANT".equals(account.getStatus())) {
            throw new BizException("E_ACCT_110", "휴면계좌 해제 대상이 아닙니다.");
        }

        if (!identityVerifier.isCompleted(request.getIdentityTicketNo())) {
            throw new BizException("E_ACCT_111", "본인확인이 완료되지 않았습니다.");
        }

        if (account.isTransactionRestricted()) {
            throw new BizException("E_ACCT_112", "거래제한 계좌는 해제할 수 없습니다.");
        }

        if (!request.isCustomerAgreed()) {
            throw new BizException("E_ACCT_113", "고객 동의가 필요합니다.");
        }

        scenarioMapper.updateDormantRelease(request);
    }

    public void changeTransferLimit(TransferLimitRequest request, User user) {
        if (!user.hasRole("LIMIT_CHANGE")) {
            throw new BizException("E_LIMIT_403", "이체한도 변경 권한이 없습니다.");
        }

        LimitPolicy policy = scenarioMapper.selectTransferLimitPolicy(request.getCustomerNo());
        if (policy == null || request.getDailyLimit() > policy.getMaxDailyLimit()) {
            throw new BizException("E_LIMIT_120", "상향 가능 한도를 초과했습니다.");
        }

        if (!identityVerifier.isIdCardVerified(request.getCustomerNo())) {
            throw new BizException("E_LIMIT_121", "신분증 진위확인이 필요합니다.");
        }

        if (request.getSecurityLevel() == null || request.getSecurityLevel().compareTo("A") > 0) {
            throw new BizException("E_LIMIT_122", "보안매체 등급이 부족합니다.");
        }

        if (policy.isMinorCustomer() && !user.hasRole("LIMIT_MINOR_APPROVE")) {
            throw new BizException("E_LIMIT_123", "미성년자는 영업점 승인 후 변경할 수 있습니다.");
        }

        scenarioMapper.updateTransferLimit(request);
    }

    public void reissueCard(CardReissueRequest request, User user) {
        if (!user.hasRole("CARD_REISSUE")) {
            throw new BizException("E_CARD_403", "카드 재발급 권한이 없습니다.");
        }

        Card card = scenarioMapper.selectReissueCard(request.getCardNo());
        if (card == null || !"LOST".equals(card.getReportStatus())) {
            throw new BizException("E_CARD_210", "분실신고가 접수되지 않았습니다.");
        }

        if (request.getDeliveryAddress() == null || request.getZipCode() == null) {
            throw new BizException("E_CARD_211", "배송지 주소를 확인하세요.");
        }

        if (card.getReissueCountThisMonth() >= 2) {
            throw new BizException("E_CARD_212", "월 재발급 가능 횟수를 초과했습니다.");
        }

        if (scenarioMapper.existsOverdueAccount(card.getCustomerNo())) {
            throw new BizException("E_CARD_213", "연체 계좌가 있어 재발급할 수 없습니다.");
        }

        scenarioMapper.insertCardReissueRequest(request);
    }

    public void extendLoan(LoanExtensionRequest request, User user) {
        if (!user.hasRole("LOAN_EXTENSION")) {
            throw new BizException("E_LOAN_403", "대출 만기연장 권한이 없습니다.");
        }

        Loan loan = scenarioMapper.selectLoanForExtension(request.getLoanNo());
        if (loan == null || "OVERDUE".equals(loan.getStatus())) {
            throw new BizException("E_LOAN_310", "연체 중인 대출은 만기연장할 수 없습니다.");
        }

        if (loan.isCreditScoreExpired()) {
            throw new BizException("E_LOAN_311", "신용평가 결과가 만료되었습니다.");
        }

        if (loan.requiresCollateralReview()) {
            throw new BizException("E_LOAN_312", "담보 재평가가 필요합니다.");
        }

        if (!request.isContractAgreed()) {
            throw new BizException("E_LOAN_313", "약정서 동의가 필요합니다.");
        }

        scenarioMapper.updateLoanMaturity(request);
    }

    public void redeemFund(FundRedemptionRequest request, User user) {
        if (!user.hasRole("FUND_REDEMPTION")) {
            throw new BizException("E_FUND_403", "펀드 환매 권한이 없습니다.");
        }

        FundAccount fund = scenarioMapper.selectFundAccount(request.getFundAccountNo());
        if (holidayCalendar.isAfterFundCutoffTime()) {
            throw new BizException("E_FUND_410", "환매 가능 시간이 아닙니다.");
        }

        if (fund == null || fund.getAvailableUnits() < request.getUnits()) {
            throw new BizException("E_FUND_411", "환매 가능 좌수가 부족합니다.");
        }

        if (fund.isBranchRestrictedProduct()) {
            throw new BizException("E_FUND_412", "영업점 환매 제한 상품입니다.");
        }

        if (!request.isRiskProfileChecked()) {
            throw new BizException("E_FUND_413", "투자성향 확인이 필요합니다.");
        }

        scenarioMapper.insertFundRedemption(request);
    }

    public void requestForeignRemittance(ForeignRemittanceRequest request, User user) {
        if (!user.hasRole("FX_REMIT")) {
            throw new BizException("E_FX_403", "외화송금 권한이 없습니다.");
        }

        if (request.getBeneficiaryName() == null || request.getBeneficiaryName().isBlank()) {
            throw new BizException("E_FX_510", "수취인 정보를 확인하세요.");
        }

        RemitLimit limit = scenarioMapper.selectRemittanceLimit(request.getCustomerNo());
        if (limit == null || request.getAmountUsd() > limit.getRemainUsd()) {
            throw new BizException("E_FX_511", "외화송금 한도를 초과했습니다.");
        }

        if (request.getDocumentNo() == null) {
            throw new BizException("E_FX_512", "증빙서류를 첨부하세요.");
        }

        if (amlChecker.isSanctionedCountry(request.getCountryCode())) {
            throw new BizException("E_FX_513", "제재국가 송금은 제한됩니다.");
        }

        scenarioMapper.insertForeignRemittance(request);
    }

    public void approveCashWithdrawal(CashWithdrawalRequest request, User user) {
        if (!user.hasRole("CASH_WITHDRAW_APPROVE")) {
            throw new BizException("E_CASH_403", "고액현금 인출 승인 권한이 없습니다.");
        }

        Account account = scenarioMapper.selectCashWithdrawalAccount(request.getAccountNo());
        if (account == null || !"ACTIVE".equals(account.getStatus())) {
            throw new BizException("E_CASH_610", "인출 가능한 계좌가 아닙니다.");
        }

        if (request.getAmount() < 10000000L) {
            throw new BizException("E_CASH_611", "고액현금 인출 대상 금액을 확인하세요.");
        }

        if (!scenarioMapper.existsCashPreCheck(request.getPreCheckNo())) {
            throw new BizException("E_CASH_612", "고액현금 사전확인이 필요합니다.");
        }

        if (!amlChecker.isCompleted(request.getAccountNo())) {
            throw new BizException("E_CASH_613", "AML 확인이 완료되지 않았습니다.");
        }

        scenarioMapper.insertCashWithdrawalApproval(request);
    }

    public void registerAutoDebit(AutoDebitRequest request, User user) {
        if (!user.hasRole("AUTO_DEBIT_REGISTER")) {
            throw new BizException("E_AUTO_403", "자동이체 등록 권한이 없습니다.");
        }

        Account account = scenarioMapper.selectAutoDebitAccount(request.getWithdrawAccountNo());
        if (account == null || !"ACTIVE".equals(account.getStatus()) || account.isExpired()) {
            throw new BizException("E_AUTO_710", "출금계좌가 만료되었거나 사용 불가 상태입니다.");
        }

        if (request.getPayerNo() == null || request.getPayerNo().length() < 8) {
            throw new BizException("E_AUTO_711", "납부자번호 형식을 확인하세요.");
        }

        if (request.getWithdrawDay() < 1 || request.getWithdrawDay() > 28) {
            throw new BizException("E_AUTO_712", "출금일은 1일부터 28일 사이로 선택하세요.");
        }

        if (scenarioMapper.existsAutoDebit(request)) {
            throw new BizException("E_AUTO_713", "이미 등록된 자동이체입니다.");
        }

        scenarioMapper.insertAutoDebit(request);
    }

    public void addCorporateUser(CorporateUserRequest request, User user) {
        if (!user.hasRole("CORP_USER_ADD")) {
            throw new BizException("E_CORP_403", "기업뱅킹 사용자 등록 권한이 없습니다.");
        }

        CorporateCustomer corporate = scenarioMapper.selectCorporateCustomer(request.getBusinessNo());
        if (corporate == null || !"NORMAL".equals(corporate.getStatus())) {
            throw new BizException("E_CORP_810", "사업자번호 상태를 확인하세요.");
        }

        if (!corporate.isAdminApproved()) {
            throw new BizException("E_CORP_811", "관리자 승인이 필요합니다.");
        }

        if (request.getOtpSerialNo() == null) {
            throw new BizException("E_CORP_812", "OTP 등록 정보를 확인하세요.");
        }

        if (scenarioMapper.existsCorporateUser(request.getBusinessNo(), request.getUserId())) {
            throw new BizException("E_CORP_813", "이미 등록된 기업뱅킹 사용자입니다.");
        }

        scenarioMapper.insertCorporateUser(request);
    }

    public void issueBalanceCertificate(BalanceCertificateRequest request, User user) {
        if (!user.hasRole("BALANCE_CERTIFICATE")) {
            throw new BizException("E_CERT_403", "잔액증명서 발급 권한이 없습니다.");
        }

        CertificateAccount account = scenarioMapper.selectCertificateAccount(request.getAccountNo());
        if (account == null || account.isSeized()) {
            throw new BizException("E_CERT_910", "압류 또는 제한 계좌는 증명서를 발급할 수 없습니다.");
        }

        if (!holidayCalendar.isBusinessClosed(request.getBaseDate())) {
            throw new BizException("E_CERT_911", "기준일 거래마감 후 발급할 수 있습니다.");
        }

        if (account.getFeeAvailableBalance() < 2000L) {
            throw new BizException("E_CERT_912", "수수료 출금 가능 잔액이 부족합니다.");
        }

        if ("EN".equals(request.getLanguage()) && account.getEnglishName() == null) {
            throw new BizException("E_CERT_913", "영문명이 등록되어 있지 않습니다.");
        }

        scenarioMapper.insertBalanceCertificateIssue(request);
    }
}
