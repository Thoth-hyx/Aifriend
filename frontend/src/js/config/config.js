const platform = 'cloud'

const CONFIG_API ={
    HTTP_URL:'',
    VAD_URL:'',
}

if (platform === 'vue'){
    CONFIG_API.HTTP_URL = 'http://127.0.0.1:8000'
    CONFIG_API.VAD_URL = 'http://localhost:5173/vad/'
}else if (platform === 'django'){
    CONFIG_API.HTTP_URL = 'http://127.0.0.1:8000'
    CONFIG_API.VAD_URL = 'http://127.0.0.1:8000/static/frontend/vad/'
}else if (platform === 'cloud'){
    CONFIG_API.HTTP_URL = 'https://app7711.acapp.acwing.com.cn'
    CONFIG_API.VAD_URL = 'https://app7711.acapp.acwing.com.cn/static/frontend/vad/'
}

CONFIG_API.HTTP_URL = import.meta.env.VITE_API_URL || CONFIG_API.HTTP_URL
CONFIG_API.VAD_URL = import.meta.env.VITE_VAD_URL || CONFIG_API.VAD_URL

export default CONFIG_API
