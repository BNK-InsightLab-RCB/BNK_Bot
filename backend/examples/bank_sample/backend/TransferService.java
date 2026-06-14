package com.example.branch.transfer;

import org.springframework.stereotype.Service;

@Service
public class TransferService {
    private final TransferMapper transferMapper;
    private final OtpService otpService;

    public TransferService(TransferMapper transferMapper, OtpService otpService) {
        this.transferMapper = transferMapper;
        this.otpService = otpService;
    }

    public void executeTransfer(TransferDto dto, User user) {
        if (!user.hasRole("TRANSFER_EXECUTE")) {
            throw new BizException("E_TRNF_403", "이체 실행 권한이 없습니다.");
        }

        if (dto.getAmount() == null || dto.getAmount().longValue() <= 0) {
            throw new BizException("E_TRNF_001", "이체금액을 확인하세요.");
        }

        Account account = transferMapper.selectAccount(dto.getFromAccountNo());
        if (account == null || !"ACTIVE".equals(account.getStatus())) {
            throw new BizException("E_TRNF_404", "출금계좌를 확인하세요.");
        }

        if (account.getBalance().compareTo(dto.getAmount()) < 0) {
            throw new BizException("E_TRNF_101", "잔액이 부족합니다.");
        }

        Long todayAmount = transferMapper.selectTodayTransferAmount(dto.getFromAccountNo());
        if (todayAmount + dto.getAmount().longValue() > 10000000L) {
            throw new BizException("E_TRNF_102", "1일 이체한도를 초과했습니다.");
        }

        if (!otpService.verify(dto.getOtpNo(), user)) {
            throw new BizException("E_TRNF_201", "OTP 인증에 실패했습니다.");
        }

        transferMapper.insertTransferHistory(dto);
        transferMapper.updateAccountBalance(dto);
    }
}
