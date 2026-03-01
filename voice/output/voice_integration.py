#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音集成模块 - 重构版本：依赖apiserver的流式TTS实现
支持接收处理好的普通文本、并发音频合成和音频播放（使用simpleaudio替换pygame）
"""
import logging
import threading
import time
from typing import Optional, Dict, Any
import sys
from pathlib import Path
from queue import Queue, Empty

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from system.config import config

logger = logging.getLogger("VoiceIntegration")


class VoiceIntegration:
    """语音集成模块 - 重构版本：依赖apiserver的流式TTS实现"""
    
    def __init__(self):
        self.provider = 'edge_tts'  # 默认使用Edge TTS
        self.tts_url = f"http://127.0.0.1:{config.tts.port}/v1/audio/speech"
        
        # 音频播放配置
        self.min_sentence_length = 5  # 最小句子长度（硬编码默认值）
        self.max_concurrent_tasks = 3  # 最大并发任务数（硬编码默认值）
        
        # 并发控制
        self.tts_semaphore = threading.Semaphore(2)  # 限制TTS请求并发数为2
        
        # 音频文件存储目录
        from system.config import get_data_dir
        self.audio_temp_dir = get_data_dir() / "audio_temp"
        self.audio_temp_dir.mkdir(parents=True, exist_ok=True)
        
        # 流式处理状态
        self.is_processing = False  # 是否正在处理
        self.sentence_queue = Queue()  # 句子队列（extractor 切割好的句子）
        self.audio_queue = Queue(maxsize=2)  # 音频队列（最多预缓冲 2 个 TTS 片段）

        # 文字-语音同步：首个 TTS 片段就绪后通知 extractor 放行文字显示
        self.first_tts_ready = threading.Event()
        
        # 播放状态控制
        self.is_playing = False
        self.current_playback = None  # 存储当前音频播放对象
        
        # 音频系统状态
        self.audio_available = False
        self._sa = None  # simpleaudio引用
        self._AudioSegment = None  # pydub的AudioSegment引用

        # 🔧 首次播放优化：暂时不启用延迟
        self.first_playback = True  # 是否是第一次播放
        self.first_playback_delay_ms = 0  # 首次播放延迟（毫秒），暂时不启用
        self.enable_timing_debug = False  # 是否启用计时debug日志（默认关闭）

        # 初始化音频系统（替换pygame）
        self._init_audio_system()
        
        # 启动音频播放工作线程
        self.audio_thread = threading.Thread(target=self._audio_player_worker, daemon=True)
        self.audio_thread.start()
        
        # 启动音频处理工作线程（持续运行）
        self.processing_thread = threading.Thread(target=self._audio_processing_worker, daemon=True)
        self.processing_thread.start()
        
        # 启动音频文件清理线程
        self.cleanup_thread = threading.Thread(target=self._audio_cleanup_worker, daemon=True)
        self.cleanup_thread.start()
        
        logger.info("语音集成模块初始化完成（重构版本 - 依赖apiserver）")

    def _init_audio_system(self):
        """初始化音频系统 - 使用pygame.mixer播放MP3（无需ffmpeg）"""
        try:
            import pygame

            # 初始化pygame mixer（可以直接播放MP3，无需ffmpeg）
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

            self._pygame = pygame
            self.audio_available = True
            logger.info("音频系统初始化成功 (pygame.mixer - 可直接播放MP3)")

        except ImportError as e:
            logger.error(f"pygame未安装: {e}，请安装: pip install pygame")
            self.audio_available = False
        except Exception as e:
            logger.error(f"音频系统初始化失败: {e}")
            self.audio_available = False

    def receive_final_text(self, final_text: str):
        """接收最终完整文本 - 按句切割后入队"""
        if not config.system.voice_enabled:
            return

        if final_text and final_text.strip():
            logger.info(f"接收最终文本: {final_text[:100]}")
            self.reset_processing_state()
            # 按句切割入队
            import re
            parts = re.split(r'(?<=[。？！；.?!;])', final_text.strip())
            for part in parts:
                part = part.strip()
                if part:
                    self.sentence_queue.put(part)

    def receive_text_chunk(self, text: str):
        """接收文本片段 - 已由 extractor 切割好，直接入 TTS 队列"""
        if not config.system.voice_enabled:
            return

        if text and text.strip():
            self.sentence_queue.put(text.strip())
            logger.debug(f"句子入队: {text[:50]}...")

    def receive_audio_url(self, audio_url: str):
        """接收音频URL - 直接播放apiserver生成的音频（保持原始逻辑）"""
        if not config.system.voice_enabled:
            return
            
        if audio_url and audio_url.strip():
            logger.info(f"接收音频URL: {audio_url}")
            # 直接播放音频
            self._play_audio_from_url(audio_url)

    def _start_audio_processing(self):
        """启动音频处理线程（保持原始逻辑）"""
        # 线程已经在初始化时启动，这里只需要设置状态
        if not self.is_processing:
            logger.debug("音频处理线程已启动，准备处理新的句子...")
        # 线程会自动从队列中获取句子进行处理
        
    def reset_processing_state(self):
        """重置处理状态，为新的对话做准备"""
        # 清空队列
        while not self.sentence_queue.empty():
            try:
                self.sentence_queue.get_nowait()
            except Empty:
                break

        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except Empty:
                break

        self.first_tts_ready.clear()
        logger.debug("语音处理状态已重置")
        
    def _audio_processing_worker(self):
        """音频处理工作线程 - 从 sentence_queue 取句子生成 TTS"""
        logger.info("音频处理工作线程启动")

        try:
            while True:
                try:
                    sentence = self.sentence_queue.get(timeout=10)
                    self.is_processing = True

                    audio_data = self._generate_audio_sync(sentence)
                    # 首个 TTS 完成（无论成败）→ 通知 extractor 放行文字显示
                    if not self.first_tts_ready.is_set():
                        self.first_tts_ready.set()
                        logger.info("首个 TTS 片段就绪，解除前端文字缓冲")
                    if audio_data:
                        self.audio_queue.put(audio_data)  # maxsize=2, 超过则阻塞等待播放消费
                        logger.debug(f"音频生成完成: {sentence[:30]}...")
                    else:
                        logger.warning(f"音频生成失败: {sentence[:30]}...")

                except Empty:
                    self.is_processing = False
                    continue

        except Exception as e:
            logger.error(f"音频处理工作线程错误: {e}")
            self.is_processing = False
        finally:
            self.is_processing = False
            logger.info("音频处理工作线程结束")

    def _generate_audio_sync(self, text: str) -> Optional[bytes]:
        """同步生成音频数据（保持原始逻辑）"""
        # 使用信号量控制并发
        if not self.tts_semaphore.acquire(timeout=10):  # 10秒超时
            logger.warning("TTS请求超时，跳过音频生成")
            return None
            
        try:
            # 文本预处理
            if not getattr(config.tts, 'remove_filter', False):
                from voice.output.handle_text import prepare_tts_input_with_context
                text = prepare_tts_input_with_context(text)
            
            if not text.strip():
                return None
                
            headers = {
                "Content-Type": "application/json"
            }
            payload = {
                "input": text,
                "voice": config.tts.default_voice or "alloy",
                "response_format": config.tts.default_format,
                "speed": config.tts.default_speed
            }

            # 认证态 → NagaBusiness 网关；否则 → 本地 edge-tts
            from apiserver import naga_auth
            if naga_auth.is_authenticated():
                tts_url = naga_auth.NAGA_MODEL_URL + "/audio/speech"
                headers["Authorization"] = f"Bearer {naga_auth.get_access_token()}"
                payload["model"] = "default"
                # NagaBusiness TTS 使用角色 voice 名称，回退到 config 或 Cherry
                from system.config import get_character_voice
                payload["voice"] = get_character_voice() or getattr(config.tts, 'naga_voice', None) or "Cherry"
            else:
                tts_url = self.tts_url  # http://127.0.0.1:{port}/v1/audio/speech
                if config.tts.require_api_key:
                    headers["Authorization"] = f"Bearer {config.tts.api_key}"

            # 使用requests进行同步调用
            import requests
            response = requests.post(
                tts_url,
                json=payload,
                headers=headers,
                timeout=30  # 硬编码超时时间（秒）
            )
            
            if response.status_code == 200:
                audio_data = response.content
                logger.debug(f"音频生成成功: {len(audio_data)} bytes")
                return audio_data
            else:
                logger.error(f"TTS API调用失败: status={response.status_code}, url={tts_url}, "
                           f"voice={payload.get('voice')}, text={text[:50]}..., "
                           f"response={response.text[:200]}")
                return None
                
        except Exception as e:
            logger.error(f"生成音频数据异常: {e}")
            return None
        finally:
            # 释放信号量
            self.tts_semaphore.release()

    def _audio_player_worker(self):
        """音频播放工作线程（保持原始线程逻辑，仅替换播放实现）"""
        logger.info("音频播放工作线程启动")
        
        # 检查音频系统是否可用
        if not self.audio_available:
            logger.error("音频系统不可用，播放线程无法启动")
            return
        
        try:
            while True:
                try:
                    # 从队列获取音频数据，保持30秒超时
                    audio_data = self.audio_queue.get(timeout=30)
                        
                    if audio_data:
                        # 播放音频数据
                        self._play_audio_data_sync(audio_data)
                        
                except Empty:
                    # 队列为空，继续等待
                    logger.debug("音频队列为空，继续等待...")
                    continue
                except Exception as e:
                    logger.error(f"音频播放工作线程错误: {e}")
                    time.sleep(0.1)
                    
        except Exception as e:
            logger.error(f"音频播放工作线程异常: {e}")
        finally:
            logger.info("音频播放工作线程结束")

    def _play_audio_data_sync(self, audio_data: bytes):
        """同步播放音频数据 - 使用pygame.mixer（无需ffmpeg）"""
        if not self.audio_available:
            logger.warning("音频系统不可用，无法播放音频")
            return

        try:
            # 🔧 首次播放计时开始
            playback_start_time = time.time()
            is_first_play = self.first_playback

            # 停止当前正在播放的音频
            if self._pygame.mixer.music.get_busy():
                self._pygame.mixer.music.stop()
                time.sleep(0.1)

            # 创建临时文件用于播放（pygame.mixer需要文件路径）
            import tempfile
            audio_format = config.tts.default_format or "mp3"
            temp_file = tempfile.mktemp(suffix=f".{audio_format}")

            # 写入音频数据
            with open(temp_file, 'wb') as f:
                f.write(audio_data)

            # ====== 商业级Live2D口型同步引擎 V2.0 ======
            # 🔧 关键修改：先启动口型同步，让引擎立即开始初始化
            self._start_live2d_lip_sync()

            # 如果需要口型同步，先加载音频数据进行分析（让引擎准备就绪）
            audio_array = None
            sample_rate = 44100

            # 尝试加载音频用于口型同步（可选功能）
            if hasattr(self, '_advanced_lip_sync_v2') or True:  # 尝试初始化
                try:
                    # 使用soundfile或wave读取音频数据用于分析
                    try:
                        import soundfile as sf
                        audio_array, sample_rate = sf.read(temp_file)
                        # 转换为单声道
                        if len(audio_array.shape) > 1:
                            audio_array = audio_array.mean(axis=1)
                        # 转换为int16格式
                        import numpy as np
                        audio_array = (audio_array * 32767).astype(np.int16)
                        logger.debug(f"使用soundfile加载音频: {len(audio_array)} 样本, {sample_rate}Hz")
                    except ImportError:
                        # soundfile不可用，尝试使用wave（仅支持WAV格式）
                        if audio_format == "wav":
                            import wave
                            import numpy as np
                            with wave.open(temp_file, 'rb') as wf:
                                sample_rate = wf.getframerate()
                                frames = wf.readframes(wf.getnframes())
                                audio_array = np.frombuffer(frames, dtype=np.int16)
                            logger.debug(f"使用wave加载音频: {len(audio_array)} 样本, {sample_rate}Hz")

                    # 初始化口型同步引擎
                    if not hasattr(self, '_advanced_lip_sync_v2') and audio_array is not None:
                        try:
                            from voice.input.voice_realtime.core.advanced_lip_sync_v2 import AdvancedLipSyncEngineV2
                            self._advanced_lip_sync_v2 = AdvancedLipSyncEngineV2(
                                sample_rate=sample_rate,
                                target_fps=60
                            )
                            logger.info("✅ TTS播放已启用商业级口型同步引擎V2.0")
                        except Exception as e:
                            logger.error(f"商业级引擎初始化失败: {e}")
                            self._advanced_lip_sync_v2 = None

                except Exception as e:
                    logger.debug(f"加载音频数据用于口型同步失败: {e}")
                    audio_array = None

            # 🔧 首次播放延迟：在口型引擎准备好后，延迟音频播放
            if self.first_playback and self.first_playback_delay_ms > 0:
                delay_seconds = self.first_playback_delay_ms / 1000.0
                if self.enable_timing_debug:
                    logger.info(f"🎯 [EdgeTTS首次播放] 口型引擎已准备，延迟 {self.first_playback_delay_ms}ms 后再播放音频")
                time.sleep(delay_seconds)
                if self.enable_timing_debug:
                    logger.info("🎯 [EdgeTTS首次播放] 延迟结束，开始播放音频")
                self.first_playback = False

            # 加载并播放音频
            load_start_time = time.time()
            self._pygame.mixer.music.load(temp_file)
            self._pygame.mixer.music.play()
            self.is_playing = True

            # 🔧 计时debug：记录加载和播放启动时间
            if is_first_play and self.enable_timing_debug:
                load_duration = (time.time() - load_start_time) * 1000
                total_startup = (time.time() - playback_start_time) * 1000
                logger.info(f"⏱️ [EdgeTTS播放计时] 音频加载耗时={load_duration:.2f}ms, 总启动时间={total_startup:.2f}ms")

            # 等待播放完成，同时更新口型
            start_time = time.time()
            lip_sync_count = 0  # 口型同步更新次数

            if audio_array is not None and self._advanced_lip_sync_v2:
                # 有音频数据，执行口型同步
                chunk_size = int(sample_rate / 60)  # 60FPS
                audio_pos = 0

                while self._pygame.mixer.music.get_busy():
                    current_time = time.time()
                    elapsed_time = current_time - start_time

                    # 根据播放时间计算当前音频位置
                    target_pos = int(elapsed_time * sample_rate)

                    # 获取当前音频块
                    if target_pos < len(audio_array):
                        chunk_start = max(0, target_pos - chunk_size // 2)
                        chunk_end = min(len(audio_array), target_pos + chunk_size // 2)
                        audio_chunk = audio_array[chunk_start:chunk_end].tobytes()

                        # 使用商业级引擎处理音频
                        if audio_chunk:
                            try:
                                # 🔧 首次播放计时：记录前5次口型同步耗时
                                if is_first_play and self.enable_timing_debug and lip_sync_count < 5:
                                    lip_sync_start = time.time()

                                self._update_live2d_with_advanced_engine(audio_chunk)

                                if is_first_play and self.enable_timing_debug and lip_sync_count < 5:
                                    lip_sync_duration = (time.time() - lip_sync_start) * 1000
                                    logger.info(f"⏱️ [EdgeTTS口型同步计时] 第{lip_sync_count+1}次更新: 耗时={lip_sync_duration:.2f}ms")
                                    lip_sync_count += 1
                            except Exception as e:
                                logger.debug(f"商业级引擎处理错误: {e}")

                    # 60FPS更新频率
                    time.sleep(1.0 / 60)

                    # 防止无限等待（5分钟超时）
                    if current_time - start_time > 300:
                        logger.warning("音频播放超时，强制停止")
                        self._pygame.mixer.music.stop()
                        break
            else:
                # 没有音频数据，仅等待播放完成
                while self._pygame.mixer.music.get_busy():
                    time.sleep(0.1)

                    # 防止无限等待
                    if time.time() - start_time > 300:
                        logger.warning("音频播放超时，强制停止")
                        self._pygame.mixer.music.stop()
                        break

            self.is_playing = False
            self._stop_live2d_lip_sync()
            logger.debug("音频播放完成")

            # 清理临时文件
            try:
                import os
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception as e:
                logger.debug(f"清理临时文件失败: {e}")

        except Exception as e:
            logger.error(f"播放音频数据失败: {e}")
            import traceback
            traceback.print_exc()
            self.is_playing = False
            self._stop_live2d_lip_sync()

            # 🔧 即使出错也标记已尝试首次播放
            if self.first_playback:
                self.first_playback = False

    def _audio_cleanup_worker(self):
        """音频文件清理工作线程（保持原始逻辑）"""
        logger.info("音频文件清理工作线程启动")
        
        while True:
            try:
                time.sleep(60)  # 每60秒清理一次（硬编码清理间隔）
                
                # 获取所有音频文件
                audio_files = list(self.audio_temp_dir.glob(f"*.{config.tts.default_format}"))
                
                # 清理文件
                files_to_clean = []
                for file_path in audio_files:
                    # 检查文件是否过旧（超过5分钟，硬编码超时时间）
                    if time.time() - file_path.stat().st_mtime > 300:
                        files_to_clean.append(file_path)
                
                if files_to_clean:
                    logger.info(f"开始清理 {len(files_to_clean)} 个音频文件")
                    for file_path in files_to_clean:
                        try:
                            file_path.unlink()
                            logger.debug(f"已删除音频文件: {file_path}")
                        except Exception as e:
                            logger.warning(f"删除音频文件失败: {file_path} - {e}")
                    
                    logger.info(f"音频文件清理完成，共清理 {len(files_to_clean)} 个文件")
                else:
                    logger.debug("本次清理检查完成，无需要清理的文件")
                    
            except Exception as e:
                logger.error(f"音频文件清理异常: {e}")
                time.sleep(5)

    def finish_processing(self):
        """完成处理 — 句子已由 extractor 切割并入队，无需再 flush 缓冲区"""
        pass

    def get_debug_info(self) -> Dict[str, Any]:
        """获取调试信息（保持原始逻辑，更新音频状态标识）"""
        return {
            "sentence_queue_size": self.sentence_queue.qsize(),
            "audio_queue_size": self.audio_queue.qsize(),
            "is_processing": self.is_processing,
            "is_playing": self.is_playing,
            "audio_available": self.audio_available,  # 替换原pygame_available
            "temp_files": len(list(self.audio_temp_dir.glob(f"*.{config.tts.default_format}")))
        }

    def _play_audio_from_url(self, audio_url: str):
        """从URL播放音频 - 使用pygame.mixer"""
        if not self.audio_available:
            logger.warning("音频系统不可用，无法播放音频URL")
            return

        try:
            import requests
            import tempfile
            import os

            # 判断是URL还是本地文件
            if audio_url.startswith("http://") or audio_url.startswith("https://"):
                # 下载音频文件
                logger.info(f"下载音频文件: {audio_url}")
                resp = requests.get(audio_url)
                temp_file = tempfile.mktemp(suffix=f".{config.tts.default_format or 'mp3'}")
                with open(temp_file, 'wb') as f:
                    f.write(resp.content)
                audio_file = temp_file
            else:
                # 本地文件路径
                audio_file = audio_url

            # 检查文件是否存在
            if not os.path.exists(audio_file):
                logger.error(f"音频文件不存在: {audio_file}")
                return

            # 读取音频文件并播放
            with open(audio_file, 'rb') as f:
                audio_data = f.read()
            self._play_audio_data_sync(audio_data)

            # 清理临时文件
            if audio_file != audio_url:
                try:
                    os.unlink(audio_file)
                except:
                    pass

        except Exception as e:
            logger.error(f"播放音频URL失败: {e}")

    # ====== Live2D嘴部同步辅助方法 ======
    def _get_live2d_widget(self):
        """获取Live2D widget引用"""
        try:
            # 通过config获取window，然后获取side widget和live2d_widget
            if hasattr(config, 'window') and config.window:
                window = config.window
                if hasattr(window, 'side') and hasattr(window.side, 'live2d_widget'):
                    live2d_widget = window.side.live2d_widget
                    # 检查是否在Live2D模式且模型已加载
                    if (hasattr(window.side, 'display_mode') and
                        window.side.display_mode == 'live2d' and
                        live2d_widget and
                        hasattr(live2d_widget, 'is_model_loaded') and
                        live2d_widget.is_model_loaded()):
                        return live2d_widget
        except Exception as e:
            logger.debug(f"获取Live2D widget失败: {e}")
        return None
    
    def _start_live2d_lip_sync(self):
        """启动Live2D嘴部同步"""
        try:
            live2d_widget = self._get_live2d_widget()
            if live2d_widget:
                live2d_widget.start_speaking()
                logger.debug("Live2D嘴部同步已启动（音频播放）")
        except Exception as e:
            logger.debug(f"启动Live2D嘴部同步失败: {e}")
    
    def _update_live2d_with_advanced_engine(self, audio_chunk: bytes):
        """使用商业级引擎更新Live2D（完整5参数控制）"""
        try:
            live2d_widget = self._get_live2d_widget()
            if not live2d_widget:
                return
            
            # 使用商业级引擎处理音频
            lip_sync_params = self._advanced_lip_sync_v2.process_audio_chunk(audio_chunk)
            
            # 应用全部5个参数
            if 'mouth_open' in lip_sync_params:
                live2d_widget.set_audio_volume(lip_sync_params['mouth_open'])
            
            if 'mouth_form' in lip_sync_params:
                live2d_widget.set_mouth_form(lip_sync_params['mouth_form'])
            
            if hasattr(live2d_widget, 'set_mouth_smile') and 'mouth_smile' in lip_sync_params:
                live2d_widget.set_mouth_smile(lip_sync_params['mouth_smile'])
            
            if hasattr(live2d_widget, 'set_eye_brow') and 'eye_brow_up' in lip_sync_params:
                live2d_widget.set_eye_brow(lip_sync_params['eye_brow_up'])
            
            if hasattr(live2d_widget, 'set_eye_wide') and 'eye_wide' in lip_sync_params:
                live2d_widget.set_eye_wide(lip_sync_params['eye_wide'])
                
        except Exception as e:
            logger.debug(f"商业级引擎更新Live2D失败: {e}")
    
    def _stop_live2d_lip_sync(self):
        """停止Live2D嘴部同步"""
        try:
            live2d_widget = self._get_live2d_widget()
            if live2d_widget:
                live2d_widget.stop_speaking()
                logger.debug("Live2D嘴部同步已停止（音频播放完成）")
        except Exception as e:
            logger.debug(f"停止Live2D嘴部同步失败: {e}")

def get_voice_integration() -> VoiceIntegration:
    """获取语音集成实例（保持原始逻辑）"""
    if not hasattr(get_voice_integration, '_instance'):
        get_voice_integration._instance = VoiceIntegration()
    return get_voice_integration._instance
