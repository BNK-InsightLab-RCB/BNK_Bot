package com.example.branch.customer;

import org.springframework.stereotype.Service;

@Service
public class CustomerService {
    private final CustomerMapper customerMapper;

    public CustomerService(CustomerMapper customerMapper) {
        this.customerMapper = customerMapper;
    }

    public CustomerDto searchCustomer(String customerNo, User user) {
        if (customerNo == null || customerNo.isBlank()) {
            throw new BizException("고객번호가 없습니다.");
        }

        CustomerDto customer = customerMapper.selectCustomer(customerNo);
        if (customer == null) {
            throw new BizException("고객이 조회되지 않습니다.");
        }

        return customer;
    }

    public void saveCustomer(CustomerDto dto, User user) {
        if (!user.hasRole("CUSTOMER_SAVE")) {
            throw new BizException("저장 권한이 없습니다.");
        }

        if (dto.getCustomerNo() == null || dto.getCustomerNo().isBlank()) {
            throw new BizException("고객번호가 없습니다.");
        }

        CustomerDto customer = customerMapper.selectCustomer(dto.getCustomerNo());
        if (customer == null) {
            throw new BizException("고객이 조회되지 않습니다.");
        }

        if ("CLOSED".equals(customer.getStatus())) {
            throw new BizException("해지 고객은 수정할 수 없습니다.");
        }

        customerMapper.updateCustomer(dto);
    }
}
