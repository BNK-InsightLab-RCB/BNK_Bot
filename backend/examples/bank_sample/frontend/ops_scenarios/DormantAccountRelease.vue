<template>
  <section>
    <h1>휴면계좌 해제</h1>
    <label>계좌번호 <input v-model="form.accountNo" /></label>
    <label>본인확인번호 <input v-model="form.identityTicketNo" /></label>
    <label>
      고객동의
      <input v-model="form.customerAgreed" type="checkbox" />
    </label>
    <button type="button" @click="releaseDormantAccount">휴면해제</button>
  </section>
</template>

<script setup lang="ts">
import axios from "axios";

const screenId = "ACCT_110";
const screenName = "휴면계좌 해제";
const menuId = "MENU_ACCOUNT_DORMANT_RELEASE";

const form = {
  accountNo: "",
  identityTicketNo: "",
  customerAgreed: false,
};

function releaseDormantAccount() {
  if (!form.accountNo) {
    alert("계좌번호를 입력하세요.");
    return;
  }
  if (!form.identityTicketNo) {
    alert("본인확인 완료 후 진행하세요.");
    return;
  }
  if (!form.customerAgreed) {
    alert("고객 동의가 필요합니다.");
    return;
  }
  return axios.post("/api/ops/dormant/release", form);
}
</script>
