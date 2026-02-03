import {defineStore} from "pinia";
import {ref} from "vue";
import valentine from "daisyui/theme/valentine/index.js";

export const userUserStore = defineStore('user',()=>{
    const id = ref(1)
    const username = ref('hyx')
    const photo = ref('http://127.0.0.1:8000/media/user/photos/default.png')
    const profile = ref('111')
    const accessToken = ref('111')

    function isLogin(){
        return !!accessToken.value
    }

    function setAccessToken(token){
        accessToken.value = token
    }

    function setUserInfo(data){
        id.value = data.user_id
        username.value = data.username
        photo.value = data.photo
        profile.value = data.profile
    }

    function logout(){
        id.value = 0
        username.value = ''
        photo.value = ''
        profile.value = ''
    }

    return{
        id,
        username,
        photo,
        profile,
        accessToken,
        setAccessToken,
        isLogin,
        setUserInfo,
        logout,
    }
})

