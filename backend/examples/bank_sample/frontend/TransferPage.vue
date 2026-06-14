<template>
  <section>
    <h1>계좌이체</h1>
    <label>
      출금계좌
      <input v-model="form.fromAccountNo" name="fromAccountNo" />
    </label>
    <label>
      입금계좌
      <input v-model="form.toAccountNo" name="toAccountNo" />
    </label>
    <label>
      이체금액
      <input v-model.number="form.amount" name="amount" />
    </label>
    <label>
      OTP
      <input v-model="form.otpNo" name="otpNo" />
    </label>
    <button type="button" @click="executeTransfer">이체실행</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "TRNF_020";
const screenName = "계좌이체";
const menuId = "MENU_TRANSFER_EXECUTE";

const form = {
  fromAccountNo: "",
  toAccountNo: "",
  amount: 0,
  otpNo: "",
};

function executeTransfer() {
  if (!form.fromAccountNo || !form.toAccountNo) {
    alert("출금계좌와 입금계좌를 입력하세요.");
    return;
  }

  if (!form.amount || form.amount <= 0) {
    alert("이체금액을 확인하세요.");
    return;
  }

  if (!form.otpNo) {
    alert("OTP 번호를 입력하세요.");
    return;
  }

  return axios.post("/api/transfer/execute", form);
}
</script>
