import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import ai_advisor

class LocalAdvisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnected_shopify_setup_never_guesses_credentials(self):
        advisor = ai_advisor.AIAdvisor()
        with patch.object(advisor, '_call_advisor_model', new_callable=AsyncMock) as model:
            answer = await advisor.chat('Grozavu', {'connected': False}, [],
                                        'Este conectat magazinul Shopify?', 'ro')
        model.assert_not_called()
        self.assertIn('date Shopify verificate', answer)
        self.assertNotIn('token', answer.lower())
        self.assertNotIn('instalează', answer.lower())

    async def test_connected_shopify_status_confirms_active_connection_with_real_facts(self):
        advisor = ai_advisor.AIAdvisor()
        snapshot = {
            'connected': True,
            'orders_30d': 2,
            'revenue_30d': 167.9,
            'orders_today': 0,
            'revenue_today': 0.0,
            'abandoned_carts': 1,
            'active_products_count': 80,
            'currency': 'EUR',
        }
        with patch.object(advisor, '_call_advisor_model', new_callable=AsyncMock) as model:
            answer = await advisor.chat('Grozavu', snapshot, [],
                                        'Este conectat magazinul Shopify?', 'ro')
        model.assert_not_called()
        self.assertIn('conectat și activ', answer)
        self.assertIn('80', answer)
        self.assertIn('167.90 EUR', answer)

    async def test_offline_reply_names_no_specific_provider(self):
        advisor = ai_advisor.AIAdvisor()
        with patch.dict(os.environ, {'JARVIS_ADVISOR_PROVIDER': 'ollama'}, clear=True), \
             patch.object(advisor, '_call_advisor_model', new_callable=AsyncMock,
                          side_effect=ai_advisor.GeminiUnavailable('offline')):
            answer = await advisor.chat('Grozavu', {'connected': False}, [], 'Cum pot crește vânzările?', 'ro')
        self.assertIn('modelul AI este indisponibil', answer)
        self.assertNotIn('Gemini indisponibil', answer)

    async def test_ollama_is_loopback_only_and_has_no_tools(self):
        response = unittest.mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'response': 'Răspuns local'}
        client = unittest.mock.MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(return_value=response)
        with patch.dict(os.environ, {'JARVIS_ADVISOR_PROVIDER':'ollama'}, clear=True), patch.object(ai_advisor.httpx,'AsyncClient',return_value=client) as constructor:
            answer = await ai_advisor.AIAdvisor()._call_advisor_model('test', json_mode=True)
        self.assertEqual(answer, 'Răspuns local')
        self.assertFalse(constructor.call_args.kwargs['trust_env'])
        self.assertEqual(client.post.call_args.args[0], 'http://127.0.0.1:11434/api/generate')
        self.assertNotIn('tools', client.post.call_args.kwargs['json'])
        self.assertEqual(client.post.call_args.kwargs['json']['format'],'json')

    async def test_render_never_calls_local_or_cloud_model(self):
        with patch.dict(os.environ, {'JARVIS_ADVISOR_PROVIDER':'ollama','RENDER':'true'}, clear=True), patch.object(ai_advisor.httpx,'AsyncClient') as client:
            with self.assertRaises(ai_advisor.GeminiUnavailable):
                await ai_advisor.AIAdvisor()._call_advisor_model('test')
            client.assert_not_called()

    async def test_gemini_default_preserves_existing_provider(self):
        advisor = ai_advisor.AIAdvisor()
        with patch.dict(os.environ, {}, clear=True), patch.object(advisor,'_call_gemini',new_callable=AsyncMock,return_value='ok'):
            self.assertEqual(await advisor._call_advisor_model('test'), 'ok')

if __name__ == '__main__': unittest.main()
