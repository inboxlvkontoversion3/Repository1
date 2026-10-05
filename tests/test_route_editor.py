from pathlib import Path

from playwright.sync_api import sync_playwright


COMPONENT_HTML = (Path(__file__).parents[1] / "components" / "route_editor" / "index.html").read_text()
ROWS = [
	{"point_index": index, "deadline": str(index), "quantity": str(index), "rest": f"row {index}"}
	for index in range(1, 5)
]


def test_drag_preview_survives_insert_swap_and_insert_targets() -> None:
	with sync_playwright() as playwright:
		browser = playwright.chromium.launch(headless=True)
		page = browser.new_page(viewport={"width": 900, "height": 500})
		page.set_content(COMPONENT_HTML)
		page.evaluate(
			"""(args) => window.dispatchEvent(new MessageEvent('message', {data: {
				type: 'streamlit:render',
				theme: {textColor: '#222', backgroundColor: '#fff', secondaryBackgroundColor: '#eee', primaryColor: '#00f'},
				args
			}}))""",
			{"rows": ROWS, "order": [1, 2, 3, 4], "pinned": []},
		)
		page.wait_for_timeout(50)
		first = page.locator(".route-row").nth(0).bounding_box()
		second = page.locator(".route-row").nth(1).bounding_box()
		last = page.locator(".route-row").nth(3).bounding_box()
		x = page.locator(".rest").nth(0).bounding_box()["x"] + 5
		page.mouse.move(x, first["y"] + first["height"] / 2)
		page.mouse.down()
		page.mouse.move(x, second["y"] + 1)
		assert page.locator(".drop-indicator").count() == 1
		page.mouse.move(x, second["y"] + second["height"] / 2)
		assert page.locator(".drop-highlight").count() == 1
		page.mouse.move(x, last["y"] + last["height"] - 1)
		assert page.locator(".drop-indicator").count() == 1
		assert page.locator(".drop-indicator").evaluate("element => element.getBoundingClientRect().height") == 3
		page.mouse.up()
		browser.close()


def test_info_button_sends_order_details_action_without_changing_pins() -> None:
	with sync_playwright() as playwright:
		browser = playwright.chromium.launch(headless=True)
		page = browser.new_page(viewport={"width": 900, "height": 500})
		page.set_content(COMPONENT_HTML)
		page.evaluate(
			"""() => window.addEventListener('message', (event) => {
				if (event.data?.type === 'streamlit:setComponentValue') {
					window.componentAction = event.data.value;
				}
			})"""
		)
		page.evaluate(
			"""(args) => window.dispatchEvent(new MessageEvent('message', {data: {
				type: 'streamlit:render',
				theme: {textColor: '#222', backgroundColor: '#fff', secondaryBackgroundColor: '#eee', primaryColor: '#00f'},
				args
			}}))""",
			{"rows": ROWS, "order": [1, 2, 3, 4], "pinned": [2]},
		)
		page.locator(".info-button").nth(1).click()
		page.wait_for_function("window.componentAction !== undefined")
		assert page.evaluate("window.componentAction.type") == "info"
		assert page.evaluate("window.componentAction.point_index") == 2
		assert page.evaluate("window.componentAction.pinned") == [2]
		browser.close()
