package com.example.branch.transfer;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class TransferController {
    private final TransferService transferService;

    public TransferController(TransferService transferService) {
        this.transferService = transferService;
    }

    @PostMapping("/api/transfer/execute")
    public ResponseEntity<Void> executeTransfer(@RequestBody TransferDto dto, User user) {
        transferService.executeTransfer(dto, user);
        return ResponseEntity.ok().build();
    }
}
